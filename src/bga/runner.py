from pathlib import Path
import threading
import time
import json

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

from .config import Profile
from .engine import Engine, NeedsAttention
from .model import STATE_NAMES, State
from .model import Match
from .store import EventLog, Store
from .vision import Vision
from .windows import InputCancelled, WindowUnavailable, WindowsBackend, launch_battle_net, pick_window, user32, input_idle_seconds


class Runner(QThread):
    message = Signal(str)
    status = Signal(str)
    preview = Signal(object)
    observation = Signal(object)
    records_changed = Signal()

    def __init__(self, config, root: Path):
        super().__init__()
        self.config,self.root = config,root
        self.stop_event,self.pause_event = threading.Event(),threading.Event()
        self.reset_requested = threading.Event()
        self.vision = None
        self.engine = None

    def stop(self):
        self.stop_event.set()

    def pause(self):
        self.pause_event.set()

    def resume(self):
        self.reset_requested.set()
        self.pause_event.clear()

    def snapshot(self, image, name):
        directory = self.root/'data'/'screenshots'
        directory.mkdir(parents=True,exist_ok=True)
        path = directory/f'{time.time_ns()}_{name}.png'
        ok, encoded = cv2.imencode('.png',image)
        if ok:
            encoded.tofile(path)
        return str(path) if ok else None

    def run(self):
        log = EventLog(self.root/'data'/'logs',self.message.emit)
        store = backend = None
        last_frame = None
        report_dir = self.root/'data'/'integration-current'
        report_dir.mkdir(parents=True,exist_ok=True)
        started=time.monotonic()
        focused_hwnd=None
        previous_snapshot=-10.0
        previous_state=None
        game_launch_deadline=None
        adapted_rect=None
        geometry_reported=None
        try:
            self.config.validate()
            profile_path = (self.root/self.config.profile_path).resolve()
            if not profile_path.is_relative_to(self.root.resolve()):
                raise ValueError('校准文件必须位于项目目录中')
            profile = Profile.load(profile_path)
            if not self.config.observe_only:
                missing = profile.missing()
                if not profile.calibrated or missing:
                    raise ValueError('真实操作尚未启用：需完成校准。缺少：'+ '、'.join(missing[:8]))
                if self.config.test_concede and any(x not in profile.anchors for x in ['menu','confirm']):
                    raise ValueError('测试退出需要 Esc 菜单和确认框模板')
                if self.config.test_concede and any(x not in profile.verified_points for x in ['concede','confirm_concede']):
                    raise ValueError('测试退出需要校准认输与确认坐标')
                if self.config.auto_sell_for_space and 'tavernkeeper' not in profile.verified_points:
                    raise ValueError('自动卖出需要校准酒馆老板头像位置')
            log.emit('正在初始化本地 OCR，首次加载可能稍慢')
            self.vision = Vision(profile,self.root)
            store = Store(self.root/'data'/'matches.sqlite3')
            self.engine = Engine(self.config,store,log)
            if self.config.resume_match_id:
                row=next((r for r in store.recent() if r['id']==self.config.resume_match_id),None)
                if not row or row['result_status'] not in ('in_progress','interrupted','attached_in_progress'):
                    raise ValueError('无法恢复指定的未完成对局')
                row.pop('rating_delta',None)
                self.engine.match=Match(**row)
                self.engine.match.ended_at=None
                self.engine.match.result_status='attached_in_progress'
                self.engine.match.evidence_path=None
                if self.config.test_concede:
                    self.engine.match.end_reason='test_concede'
                    self.engine.concede_sent=True
                elif self.engine.match.end_reason=='interrupted':
                    self.engine.match.end_reason='normal'
                self.engine.last_rating=self.engine.match.rating_before
                log.emit('恢复本机未完成对局记录',match_id=self.engine.match.id)
            backend = WindowsBackend(self.stop_event,self.pause_event)
            log.emit('只观察模式' if self.config.observe_only else '真实操作模式；F8 暂停，F9 停止')
            launched_at = None
            last_reported = None
            f8_down = False
            while not self.stop_event.is_set():
                if self.config.integration_seconds and time.monotonic()-started>=self.config.integration_seconds:
                    log.emit('达到整体测试时长，停止本次程序运行')
                    break
                command_path=report_dir/'control.json'
                if command_path.exists():
                    try:
                        command=json.loads(command_path.read_text(encoding='utf-8-sig')).get('command')
                        if command=='stop':self.stop()
                        elif command=='pause':self.pause()
                        elif command=='resume':self.resume()
                        elif command=='reload_profile':
                            self.vision.profile=Profile.load(profile_path)
                            self.vision.cache.clear()
                            self.engine.reset_observation()
                            self.pause_event.clear()
                            log.emit('已重新读取本机校准；保留当前对局')
                        command_path.unlink()
                    except (OSError,ValueError):
                        pass
                f8_now = bool(user32.GetAsyncKeyState(0x77)&0x8000)
                if f8_now and not f8_down:
                    self.pause_event.set()
                f8_down=f8_now
                if user32.GetAsyncKeyState(0x78)&0x8000:
                    self.stop_event.set()
                    break
                if self.pause_event.is_set():
                    self.status.emit('已暂停；恢复后将重新识别')
                    self.stop_event.wait(.15)
                    continue
                if self.reset_requested.is_set():
                    self.engine.reset_observation()
                    focused_hwnd=None
                    self.reset_requested.clear()
                try:
                    target = pick_window()
                    if target is None:
                        if self.config.auto_launch and not self.config.observe_only and launched_at is None:
                            from .discovery import detect_battle_net
                            detected,source=detect_battle_net(self.config.battle_net_path)
                            if not detected:raise NeedsAttention(source)
                            self.config.battle_net_path=detected
                            log.emit('已检测战网启动路径',path=detected,source=source)
                            launch_battle_net(detected)
                            launched_at=time.monotonic()
                            log.emit('已请求启动战网，等待窗口')
                        if launched_at and time.monotonic()-launched_at>90:
                            raise NeedsAttention('战网启动 90 秒后仍未发现目标窗口')
                        self.status.emit('等待战网 / 炉石窗口')
                        self.stop_event.wait(self.config.poll_seconds)
                        continue
                    if self.config.focus_on_start and target.hwnd!=focused_hwnd:
                        if self.config.recover_focus and user32.GetForegroundWindow()!=target.hwnd and input_idle_seconds()<2:
                            self.status.emit('等待键鼠空闲 2 秒后恢复游戏前台；F8 暂停')
                            self.stop_event.wait(.25)
                            continue
                        target.activate()
                        self.stop_event.wait(.4)
                        focused_hwnd=target.hwnd
                    if target.kind=='game' and self.config.auto_adapt_resolution:
                        if self.config.observe_only:
                            # Observation must not resize third-party windows.
                            geometry=dict(client_rect=target.rect(),changed=False,observe_only=True)
                        else:
                            geometry=target.adapt_resolution(self.vision.profile.aspect_ratio)
                        signature=(target.hwnd,tuple(geometry['client_rect']))
                        if signature!=adapted_rect:
                            self.engine.reset_observation();adapted_rect=signature
                        if geometry!=geometry_reported:
                            log.emit('分辨率适配检查',**geometry);geometry_reported=geometry
                    captured_at=time.monotonic()
                    frame,rect = backend.screenshot(target)
                    if target.kind=='game':
                        game_launch_deadline=None
                    last_frame=frame
                    analysis_started=time.monotonic()
                    self.vision.inspect_point=(self.engine.hand_probe['point'] if self.engine.hand_probe and self.engine.hand_probe.get('stage')=='inspect' else None)
                    self.vision.inspect_source=self.engine.hand_probe.get('source','hand') if self.engine.hand_probe else 'hand'
                    self.vision.inspect_shop_spells=self.config.test_shop_spells
                    obs=self.vision.analyze(frame,target.kind)
                    analysis_ms=round((time.monotonic()-analysis_started)*1000,1)
                    obs.captured_at=captured_at
                    self.preview.emit(frame)
                    ready=self.engine.observe(obs)
                    label=f'{STATE_NAMES[obs.state]} · {obs.confidence:.0%} · '+('模板确认' if obs.trusted else '待校准 / 仅提示')
                    self.status.emit(label)
                    self.observation.emit(dict(state=obs.state.value,confidence=obs.confidence,trusted=obs.trusted,metrics=obs.metrics,
                                              heroes=obs.available_heroes,board=obs.board_count,text=obs.evidence,completed=self.engine.completed))
                    telemetry=dict(state=obs.state.value,confidence=obs.confidence,trusted=obs.trusted,
                                   metrics=obs.metrics,heroes=obs.available_heroes,board=obs.board_count,
                                   shop=obs.shop_minions,shop_spells=obs.shop_spells,hand=obs.hand_minions,text=obs.evidence,
                                   completed=self.engine.completed,paused=self.pause_event.is_set(),time=time.time())
                    telemetry['analysis_ms']=analysis_ms
                    (report_dir/'observation.json').write_text(json.dumps(telemetry,ensure_ascii=False,indent=2),encoding='utf-8')
                    if obs.state!=previous_state or time.monotonic()-previous_snapshot>=8:
                        cv2.imencode('.png',frame)[1].tofile(report_dir/'latest.png')
                        if obs.state==State.CHOICE or obs.metrics.get('targeting_arrow'):
                            self.snapshot(frame,'interaction_'+obs.state.value)
                        if obs.state!=previous_state:
                            self.snapshot(frame,'state_'+obs.state.value)
                        previous_snapshot=time.monotonic()
                        previous_state=obs.state
                    if self.engine.match and obs.state==State.RESULT and obs.trusted and self.engine.result_frames>=3 and not self.engine.match.evidence_path:
                        self.engine.match.evidence_path=self.snapshot(frame,self.engine.match.id)
                        store.save(self.engine.match)
                        log.emit('保存结算画面证据',match_id=self.engine.match.id,metrics=obs.metrics,ocr_text=obs.evidence,
                                 confidence=obs.confidence,evidence_path=self.engine.match.evidence_path)
                    self.records_changed.emit()
                    if self.engine.done:
                        log.emit('达到配置局数，已停止')
                        break
                    if ready:
                        previous_action=self.engine.last_action
                        feedback=(previous_action is not None and self.engine.feedback(previous_action,self.engine.before_action,obs))
                        action=self.engine.decide(obs)
                        if feedback and self.engine.last_action is None:
                            evidence=self.snapshot(frame,'after_'+previous_action.target)
                            log.emit('动作反馈证据',target=previous_action.target,state=obs.state.value,metrics=obs.metrics,
                                     board=obs.board_count,evidence_path=evidence)
                        if action:
                            evidence=self.snapshot(frame,'before_'+action.target)
                            log.emit('动作前观测',state=obs.state.value,metrics=obs.metrics,board=obs.board_count,
                                     hand=obs.hand_minions,shop=obs.shop_minions,evidence_path=evidence,
                                     target=action.target,point=obs.targets.get(action.target),
                                     destination=action.destination,destination_point=obs.targets.get(action.destination),window_rect=rect)
                            backend.execute(target,action,obs,rect)
                            self.engine.sent(action,obs)
                            if action.target=='launcher_play':
                                game_launch_deadline=time.monotonic()+90
                    last_reported=None
                except InputCancelled:
                    continue
                except (WindowUnavailable,NeedsAttention) as error:
                    message=str(error)
                    if isinstance(error,WindowUnavailable) and self.config.recover_focus and self.config.focus_on_start and ('不在前台' in message or '无法激活目标窗口' in message):
                        if message!=last_reported:
                            log.emit('目标失去前台，等待键鼠空闲后自动恢复；F8 暂停','WARNING')
                            last_reported=message
                        focused_hwnd=None
                        self.stop_event.wait(.25)
                        continue
                    if isinstance(error,WindowUnavailable) and game_launch_deadline and time.monotonic()<game_launch_deadline:
                        self.status.emit('等待炉石启动窗口完成切换')
                        self.stop_event.wait(.6)
                        continue
                    if message != last_reported:
                        log.emit(message,'WARNING')
                        last_reported=message
                        if last_frame is not None:
                            self.snapshot(last_frame,'attention')
                    self.status.emit(message)
                    self.pause_event.set()
                    (report_dir/'attention.json').write_text(json.dumps(dict(time=time.time(),paused=True,error=message),ensure_ascii=False),encoding='utf-8')
                self.stop_event.wait(min(.2,self.config.poll_seconds) if self.engine.state==State.HERO else self.config.poll_seconds)
        except Exception as error:
            log.emit(f'{type(error).__name__}: {error}','ERROR')
            self.status.emit(f'运行失败：{error}')
        finally:
            try:
                if self.engine:
                    self.engine.interrupt()
                if store:
                    store.close()
                if backend:
                    backend.close()
            except Exception as error:
                self.message.emit(f'清理错误：{error}')
            self.records_changed.emit()
            (report_dir/'finished.json').write_text(json.dumps(dict(time=time.time(),
                completed=self.engine.completed if self.engine else 0,
                reached_target=bool(self.engine and self.engine.done),paused=self.pause_event.is_set()),indent=2),encoding='utf-8')

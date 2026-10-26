"""Deterministic decisions, independent from any Windows input."""
import time
import uuid
import re

from .config import Config
from .model import Action, Match, Observation, State, hand_marks_match, TARGETED_HAND_KINDS
from .store import now_iso


class NeedsAttention(RuntimeError):
    def __init__(self,message,*,recoverable=False):
        super().__init__(message)
        self.recoverable=recoverable


class Engine:
    def __init__(self, config: Config, store, log, clock=time.monotonic):
        self.config, self.store, self.log, self.clock = config, store, log, clock
        self.state = State.UNKNOWN
        self.state_since = clock()
        self.candidate, self.stable = State.UNKNOWN, 0
        self.last_metrics = {}
        self.confirmed_metrics = {}
        self.match: Match | None = None
        self.completed = 0
        self.last_rating = None
        self.hero_clicked = None
        self.hero_attempts = 0
        self.turn_actions = 0
        self.last_action_time = -1000.0
        self.last_action = None
        self.before_action = None
        self.last_signature = None
        self.failures = 0
        self.result_frames = 0
        self.lobby_frames = 0
        self.recruit_since = None
        self.done = False
        self.concede_sent = False
        self.board_unknown_since = None
        self.target_pending_since = None
        self.hand_probe=None
        self.pending_hand_play=None
        self.hand_skipped=set()
        self.shop_spell_skipped=set()
        self.shop_spell_bought=False
        self.probes_this_turn=0
        self.probe_cursor=0
        self.sold_for_space=False
        self.recovery=None
        self.recovery_streak=0
        self.match_play_seen=False

    def reset_observation(self):
        self.board_unknown_since=None
        self.hand_probe=None
        self.pending_hand_play=None
        self.hand_skipped.clear()
        self.probes_this_turn=0
        self.probe_cursor=0
        self.stable = 0
        self.last_metrics = {}
        self.confirmed_metrics = {}
        self.state_since = self.clock()
        self.last_action = None
        self.last_signature = None
        if self.recovery and self.recovery['stage']!='failed':
            self.recovery['started']=self.clock()

    def begin_recovery(self,obs,error,window_kind='game'):
        """Only explicitly recoverable engine failures may request concession."""
        if (not self.config.auto_concede_on_error or self.config.observe_only or self.done
                or not isinstance(error,NeedsAttention) or not error.recoverable
                or self.recovery or not self.match or self.match.ended_at
                or not self.match_play_seen or window_kind!='game'
                or obs.state not in (State.RECRUIT,State.CHOICE,State.COMBAT,State.UNKNOWN)
                or self.recovery_streak>=self.config.max_consecutive_recoveries
                or not {'concede','confirm_concede'}<=obs.targets.keys()):
            return False
        self.recovery=dict(stage='open_menu',started=self.clock(),last_sent=-1000.0,
                           escapes=0,concede_attempts=0,confirm_attempts=0)
        self.match.recovery_reason=str(error)
        self.store.save(self.match)
        self.hand_probe=None
        self.pending_hand_play=None
        self.target_pending_since=None
        self.last_action=None
        self.log.emit('准备异常认输，等待确认菜单','WARNING',match_id=self.match.id,reason=str(error))
        return True

    def recovery_action(self,obs):
        recovery=self.recovery
        if recovery['stage']=='failed' or self.clock()-recovery['started']>90:
            recovery['stage']='failed'
            raise NeedsAttention('异常认输未能在 90 秒内完成，已暂停，请检查菜单或结算')
        if obs.state in (State.MAIN,State.MODES,State.ENTRY,State.LAUNCHER,State.QUEUE,State.HERO):
            recovery['stage']='failed'
            raise NeedsAttention('异常恢复时已离开当前对局，已暂停核对记录')
        if obs.state==State.MENU and obs.trusted and recovery['stage'] in ('open_menu','wait_confirm'):
            if recovery['concede_attempts'] and self.clock()-recovery['last_sent']<8:return None
            if not recovery['escapes']:
                raise NeedsAttention('异常认输尚未请求菜单，已暂停')
            if recovery['concede_attempts']>=3:
                recovery['stage']='failed'
                raise NeedsAttention('异常认输按钮连续无反馈，已暂停')
            return self.action('click','异常恢复：点击认输',obs,'concede')
        if obs.state==State.CONFIRM:
            if not obs.trusted:return None
            if recovery['stage'] not in ('wait_confirm','wait_result') or not self.concede_sent:
                raise NeedsAttention('异常恢复中出现未预期的确认框，已暂停')
            if recovery['confirm_attempts'] and self.clock()-recovery['last_sent']<8:return None
            if recovery['confirm_attempts']>=3:
                recovery['stage']='failed'
                raise NeedsAttention('异常认输确认连续无反馈，已暂停')
            return self.action('click','异常恢复：确认认输',obs,'confirm_concede')
        if recovery['stage']=='open_menu':
            if self.clock()-recovery['last_sent']<8:return None
            if recovery['escapes']>=3:
                recovery['stage']='failed'
                raise NeedsAttention('异常恢复未能识别认输菜单，已暂停')
            # Escape may first cancel a targeting arrow or hide a choice. No
            # mouse click is permitted until a trusted menu has been observed.
            return self.action('key','异常恢复：打开 Esc 菜单',obs,key='Escape')
        return None

    def signature(self, obs):
        return (obs.state, tuple(sorted(obs.metrics.items())), tuple(obs.hand_minions), tuple(obs.shop_minions), obs.board_count)

    def restore_concession(self):
        if self.match and self.match.end_reason=='auto_recovery':
            self.concede_sent=True
            self.recovery_streak=1
            self.match_play_seen=True
            self.recovery=dict(stage='wait_confirm',started=self.clock(),last_sent=-1000.0,
                               escapes=1,concede_attempts=1,confirm_attempts=0)

    def refresh_consumed_hand(self, obs):
        """Re-inspect shifted cards only after a verified cast has completed."""
        pending=self.pending_hand_play
        if not pending or obs.state!=State.RECRUIT or obs.metrics.get('targeting_arrow')==1:
            return
        if pending.get('target_expected') and not pending.get('target_clicked'):
            return
        old=pending.get('precast_hand_count')
        count=self.confirmed_metrics.get('hand_count')
        old_board=pending.get('precast_board_count')
        acquired=(pending.get('precast_hand_kind')=='targeted_acquire'
                  and obs.metrics.get('targeted_acquire_resolved')==1)
        if pending.get('precast_hand_kind')=='targeted_acquire' and not acquired:return
        minion_played=(pending.get('precast_hand_kind')=='minion' and old_board is not None
                       and obs.board_count is not None and obs.board_count>old_board)
        if not minion_played and not acquired and (old is None or count is None or count>=old):
            return
        if (not minion_played and pending.get('precast_hand_kind')=='minion' and pending.get('card_mark')
                and any(hand_marks_match(pending['card_mark'],mark) for mark in obs.hand_marks.values())):
            return
        if pending.get('precast_hand_kind') in TARGETED_HAND_KINDS:
            self.target_pending_since=None
        self.pending_hand_play=None
        self.hand_probe=None
        self.hand_skipped.clear()
        # Three failed inspections are allowed per unchanged hand, rather
        # than limiting a whole recruit phase to three inspections.
        self.probes_this_turn=0
        self.probe_cursor=0

    def feedback(self, action, before, after):
        """Only action-specific feedback counts as success, not any changed OCR."""
        if action.target in ('hero_2','hero_3'):
            return after.metrics.get('hero_selected_slot') == int(action.target[-1])
        if action.target == 'upgrade':
            old,new=before.metrics.get('tavern_tier'),after.metrics.get('tavern_tier')
            return old is not None and new is not None and new>old
        if action.target in ('friendly_target','shop_spell_target'):
            return after.state==State.RECRUIT and after.metrics.get('targeting_arrow')==0
        if action.target=='sell_minion':
            old=before.metrics.get('gold');new=self.confirmed_metrics.get('gold')
            return (after.state==State.RECRUIT and before.board_count==7 and after.board_count==6
                    and old is not None and new is not None and new>=old+1)
        if action.target=='inspected_hand':
            if before.metrics.get('precast_hand_kind')=='minion':
                old_board=before.metrics.get('precast_board_count')
                if old_board is not None and after.board_count is not None and after.board_count>old_board:return True
                mark=before.hand_marks.get('inspected_hand')
                if mark and any(hand_marks_match(mark,current) for current in after.hand_marks.values()):return False
            if before.metrics.get('precast_hand_kind') in TARGETED_HAND_KINDS and after.metrics.get('targeting_arrow')==1:
                return False
            if before.metrics.get('precast_hand_kind')=='targeted_acquire':
                return after.metrics.get('targeted_acquire_resolved')==1
            count=self.confirmed_metrics.get('hand_count')
            old=before.metrics.get('precast_hand_count')
            if before.metrics.get('precast_hand_kind')=='steal':
                previous_shop=before.metrics.get('shop_card_count')
                current_shop=self.confirmed_metrics.get('shop_card_count')
                return (after.state==State.RECRUIT and previous_shop is not None and current_shop==previous_shop-1
                        and old is not None and count is not None and count>=old)
            old_gold,new_gold=before.metrics.get('gold'),after.metrics.get('gold')
            return (count is not None and old is not None and count<old) or (old_gold is not None and new_gold is not None and new_gold>old_gold)
        if action.target=='inspected_shop_spell':
            old,new=before.metrics.get('gold'),after.metrics.get('gold')
            previous_hand=before.metrics.get('hand_count')
            current_hand=self.confirmed_metrics.get('hand_count')
            return ((old is not None and new is not None and new<old) or
                    (previous_hand is not None and current_hand is not None and current_hand>previous_hand))
        if action.target=='choice_1':
            return after.state!=before.state or after.metrics.get('choice_confirm_ready')==1
        if action.kind == 'drag' and action.target.startswith('shop_'):
            old,new=before.metrics.get('gold'),after.metrics.get('gold')
            return len(after.hand_minions)>len(before.hand_minions) or (old is not None and new is not None and new<old)
        if action.kind == 'drag' and action.target.startswith('hand_'):
            return (before.board_count is not None and after.board_count is not None and after.board_count>before.board_count) or len(after.hand_minions)<len(before.hand_minions)
        return after.state != before.state

    def observe(self, obs: Observation):
        pending=self.pending_hand_play
        if pending and pending.get('precast_hand_kind')=='targeted_acquire':
            mark=pending.get('card_mark')
            gone=(mark is not None and bool(obs.hand_marks)
                  and not any(hand_marks_match(mark,current) for current in obs.hand_marks.values()))
            clear=(obs.state==State.RECRUIT and obs.trusted and obs.metrics.get('targeting_arrow')==0
                   and (pending.get('target_clicked') or gone))
            pending['clear_frames']=pending.get('clear_frames',0)+1 if clear else 0
            if pending['clear_frames']>=2:obs.metrics['targeted_acquire_resolved']=1
        if self.hand_probe and self.hand_probe.get('stage')=='ready' and self.hand_probe.get('mark') is not None:
            matched=self.inspected_hand_candidate(obs) if obs.state==State.RECRUIT and obs.trusted else None
            self.hand_probe['ready_frames']=self.hand_probe.get('ready_frames',0)+1 if matched else 0
        if obs.state == self.candidate:
            self.stable += 1
        else:
            self.candidate, self.stable = obs.state, 1
            self.last_metrics = {}
            self.confirmed_metrics = {}
        # Numeric values must be seen twice, within the same state.
        for key, value in obs.metrics.items():
            if value is not None and self.last_metrics.get(key) == value:
                self.confirmed_metrics[key] = value
            else:
                self.confirmed_metrics.pop(key, None)
        self.last_metrics = dict(obs.metrics)
        if self.stable < self.config.stable_frames:
            return False
        if obs.state != self.state:
            old = self.state
            self.state, self.state_since = obs.state, self.clock()
            self.last_action = None
            self.last_signature = None
            self.failures = 0
            self.board_unknown_since=None
            self.log.emit(f'状态：{old.value} → {self.state.value}', confidence=obs.confidence)
            if obs.state == State.RECRUIT and old != State.RECRUIT:
                self.turn_actions = 0
                self.recruit_since = self.clock()
            if obs.state in (State.COMBAT,State.RESULT,State.LOBBY):
                self.target_pending_since=None
                self.hand_probe=None
                self.pending_hand_play=None
                self.hand_skipped.clear()
                self.shop_spell_skipped.clear()
                self.shop_spell_bought=False
                self.probes_this_turn=0
                self.sold_for_space=False
        if self.config.observe_only:
            return True
        if obs.board_count is not None:
            self.board_unknown_since=None
        if not obs.trusted:
            return True
        if obs.state in (State.HERO, State.RECRUIT, State.COMBAT) and self.match is None:
            self.match = Match(uuid.uuid4().hex, now_iso(), rating_before=self.last_rating)
            if obs.state != State.HERO:
                self.match.result_status = 'attached_in_progress'
                self.match.rating_before = None
            self.store.save(self.match)
        if self.match and obs.state in (State.RECRUIT,State.CHOICE,State.COMBAT):
            self.match_play_seen=True
        if obs.state == State.RESULT and self.match:
            self.result_frames += 1
            self.match.placement = self.confirmed_metrics.get('placement', self.match.placement)
            if self.confirmed_metrics.get('rating') is not None:
                self.match.rating_after = self.confirmed_metrics['rating']
            self.match.ended_at = self.match.ended_at or now_iso()
            self.match.result_status = 'awaiting_lobby'
            self.store.save(self.match)
        if obs.state == State.LOBBY:
            rating = self.confirmed_metrics.get('rating')
            if self.match and self.match.ended_at:
                self.lobby_frames += 1
                if rating is not None or self.lobby_frames >= 4:
                    self.match.rating_after = rating if rating is not None else self.match.rating_after
                    self.match.result_status = ('complete' if self.match.placement is not None and self.match.rating_after is not None else 'partial')
                    self.store.save(self.match)
                    self.completed += 1
                    recovered=self.match.end_reason=='auto_recovery'
                    self.log.emit(f'已完成 {self.completed} 局；名次 {self.match.placement}；分数 {self.match.rating_after}',match_id=self.match.id)
                    self.match = None
                    self.recovery=None
                    self.match_play_seen=False
                    if not recovered:self.recovery_streak=0
                    self.concede_sent = False
                    self.hero_clicked = None
                    self.hero_attempts = self.result_frames = self.lobby_frames = 0
                    if recovered and self.recovery_streak>=self.config.max_consecutive_recoveries:
                        raise NeedsAttention(f'连续 {self.recovery_streak} 局异常认输，已暂停，请检查重复出现的问题')
            elif self.match:
                if self.concede_sent and (rating is not None or self.stable>=max(4,self.config.stable_frames)):
                    self.match.ended_at=now_iso()
                    self.match.rating_after=rating
                    self.match.result_status='awaiting_lobby'
                    self.store.save(self.match)
                    self.log.emit('未捕获结算名次；保留空名次并核对大厅积分','WARNING',match_id=self.match.id)
                elif not self.concede_sent:
                    raise NeedsAttention('未观察到结算就返回大厅，当前场需检查，已停止自动开始')
            if rating is not None:
                self.last_rating = rating
            if self.config.max_matches and self.completed >= self.config.max_matches:
                self.done = True
        return True

    def action(self, kind, label, obs, target='', destination='', key=''):
        if target and target not in obs.targets:
            raise NeedsAttention(f'缺少已校准的操作坐标：{target}')
        if destination and destination not in obs.targets:
            raise NeedsAttention(f'缺少已校准的目标坐标：{destination}')
        return Action(kind,label,target,destination,key,obs.state,obs.captured_at)

    def inspected_hand_candidate(self,obs):
        probe=self.hand_probe
        if not probe or probe.get('mark') is None:return None
        px,py=probe['point']
        candidates=[name for name in obs.hand_minions if abs(obs.targets[name][0]-px)<.025
                    and abs(obs.targets[name][1]-py)<.025
                    and hand_marks_match(probe['mark'],obs.hand_marks.get(name))]
        return min(candidates,key=lambda n:abs(obs.targets[n][0]-px)+abs(obs.targets[n][1]-py)) if candidates else None

    def decide(self, obs: Observation):
        if self.config.observe_only or self.done:
            return None
        if self.clock() - self.last_action_time < self.config.action_seconds:
            return None
        if self.stable < self.config.stable_frames or obs.state != self.state:
            return None
        if obs.state == State.AUTH:
            raise NeedsAttention('检测到账号认证，请用户手动处理')
        if (self.recovery and self.clock()-self.recovery['started']>90
                and not (obs.state==State.RESULT and obs.trusted and self.match and self.match.ended_at)):
            self.recovery['stage']='failed'
            raise NeedsAttention('异常认输未能在 90 秒内完成，已暂停，请检查菜单或结算')
        if self.recovery and obs.state not in (State.RESULT,State.LOBBY,State.DISCONNECT,State.NOTICE):
            return self.recovery_action(obs)
        if obs.state==State.UNKNOWN and self.hand_probe and self.hand_probe.get('stage')=='inspect':
            # A tooltip opened by our own hover can hide the tavern anchor.
            # Only move away here; any click/drag still needs a fresh trusted frame.
            self.hand_probe['kind']=obs.metrics.get('hand_card_kind','unknown')
            obs.targets['clear_tooltip']=(.97,.35)
            return self.action('hover','收起遮挡识别区域的手牌说明',obs,'clear_tooltip')
        if not obs.trusted or obs.state == State.UNKNOWN:
            if self.clock() - self.state_since > self.config.state_timeout:
                raise NeedsAttention('画面长期无法可靠识别，需要检查模板和窗口状态',recoverable=True)
            return None
        self.refresh_consumed_hand(obs)
        if (obs.state==State.RECRUIT and self.pending_hand_play
                and self.pending_hand_play.get('precast_hand_kind')=='targeted_acquire'
                and obs.metrics.get('targeting_arrow')==0
                and (self.pending_hand_play.get('target_clicked') or self.pending_hand_play.get('clear_frames',0)>0)):
            return None
        if obs.state==State.RECRUIT and obs.metrics.get('targeting_arrow')==1:
            context=(self.target_pending_since is not None or
                     self.pending_hand_play and self.pending_hand_play.get('precast_hand_kind') in TARGETED_HAND_KINDS or
                     re.search(r'选择一个|获得[+＋]',obs.evidence))
            if not context:return None
            if not self.last_action or self.last_action.target not in ('friendly_target','shop_spell_target'):
                acquire=self.pending_hand_play and self.pending_hand_play.get('precast_hand_kind')=='targeted_acquire'
                if (obs.metrics.get('friendly_target_verified')==1 or obs.board_count and not acquire) and 'friendly_target' in obs.targets:
                    if acquire and 'highlighted_friendly_target' in obs.targets:
                        obs.targets['friendly_target']=obs.targets['highlighted_friendly_target']
                    return self.action('click','选择已高亮的友方随从目标',obs,'friendly_target')
                if (self.pending_hand_play and self.pending_hand_play.get('precast_hand_kind')=='targeted_acquire'
                        and obs.metrics.get('shop_target_verified')==1 and 'shop_spell_target' in obs.targets):
                    return self.action('click','为主厨甄选选择已高亮的酒馆随从',obs,'shop_spell_target')
                return None
            if self.clock()-self.last_action_time>=8:
                raise NeedsAttention('指向性效果未完成目标选择，已暂停',recoverable=True)
            return None
        if self.last_action and self.last_action.target=='hero_confirm' and obs.state==State.HERO:
            # Confirmation may leave the ready/waiting overlay up until all
            # eight players finish. Never select or confirm again while waiting.
            if self.clock()-self.last_action_time>150:
                raise NeedsAttention('确认英雄后等待开局超时')
            return None
        if self.last_action and not self.feedback(self.last_action,self.before_action,obs):
            if self.clock()-self.last_action_time < 8:
                return None
            self.failures += 1
            self.last_action = None
            if self.failures >= 3:
                raise NeedsAttention('连续操作后没有观察到预期变化，已暂停',recoverable=True)
        elif self.last_action:
            self.log.emit('已观察到动作反馈',action=self.last_action.label)
            self.failures = 0
            self.last_action = None
        mapping = {
            State.LAUNCHER: ('launcher_play','从战网启动炉石传说'),
            State.ENTRY: ('entry_continue','点击游戏入口'),
            State.NOTICE: ('notice_close','关闭已识别的公告或任务弹窗'),
            State.MAIN: ('main_modes','打开模式入口'),
            State.MODES: ('mode_battlegrounds','进入酒馆战棋'),
            State.DISCONNECT: ('reconnect','尝试重新连接'),
        }
        if obs.state in mapping:
            target,label = mapping[obs.state]
            return self.action('click',label,obs,target)
        if obs.state == State.LOBBY:
            if self.match is not None or self.stable < max(4,self.config.stable_frames):
                return None
            return self.action('click','开始匹配',obs,'lobby_play')
        if obs.state == State.HERO:
            if self.hero_clicked is not None:
                if obs.metrics.get('hero_selected_slot') == self.hero_clicked:
                    return self.action('click','确认已选英雄',obs,'hero_confirm')
                if self.clock()-self.last_action_time > 15:
                    raise NeedsAttention('英雄选择后未验证到高亮，请校准 hero_selected 标记')
                return None
            allowed = set(obs.available_heroes) & {2,3}
            if not allowed:
                if self.clock()-self.state_since > 15:
                    raise NeedsAttention('无法确认中间两名英雄的可选状态')
                return None
            slot = self.config.preferred_hero if self.config.preferred_hero in allowed else min(allowed)
            return self.action('click',f'选择第 {slot} 个可用英雄',obs,f'hero_{slot}')
        if obs.state == State.RESULT:
            if not self.match or not self.match.ended_at:
                raise NeedsAttention('没有当前场记录，不能自动跳过无法归属的结算')
            # Allow up to six stable result observations for OCR before dismissing.
            if self.result_frames < 3 or (self.match.placement is None and self.result_frames < 6):
                return None
            return self.action('click','结算已记录，返回大厅',obs,'result_continue')
        if obs.state == State.MENU:
            if self.config.test_concede and self.match:
                return self.action('click','测试：点击认输',obs,'concede')
            raise NeedsAttention('出现 Esc 菜单，请手动处理或开启测试退出')
        if obs.state == State.CONFIRM:
            if self.config.test_concede and self.match and self.match.end_reason == 'test_concede':
                return self.action('click','测试：确认认输',obs,'confirm_concede')
            raise NeedsAttention('意外确认对话框，需要检查')
        if obs.state == State.CHOICE:
            if obs.metrics.get('choice_confirm_ready')==1:
                return self.action('click','确认已选择的局内选项',obs,'choice_confirm')
            if obs.metrics.get('choice_kind')=='hero_power':
                return self.action('click','选择英雄技能',obs,'choice_1')
            return self.action('click','处理已识别的发现选项',obs,'choice_1')
        if obs.state == State.RECRUIT:
            if self.target_pending_since is not None:
                if obs.metrics.get('targeting_arrow')==1:
                    if (obs.board_count or obs.metrics.get('friendly_target_verified')==1) and 'friendly_target' in obs.targets:
                        return self.action('click','为已选择的指向性效果选取友方随从',obs,'friendly_target')
                    return None
                if self.clock()-self.target_pending_since<8:
                    return None
                self.log.emit('选择后未验证到指向箭头，未发送随从目标点击','WARNING')
                self.target_pending_since=None
            if self.concede_sent:
                # Concession returns through a few live-board animation frames.
                # Any extra shop/board click here can dismiss the result banner.
                if self.clock()-self.state_since>90:
                    raise NeedsAttention('认输后未进入结算，请检查游戏状态')
                return None
            if self.config.test_concede and self.recruit_since is not None and self.clock()-self.recruit_since >= self.config.concede_after_seconds:
                return self.action('key','测试：打开 Esc 菜单',obs,key='Escape')
            if self.turn_actions >= self.config.max_actions_per_turn:
                return None
            gold = self.confirmed_metrics.get('gold')
            cost = self.confirmed_metrics.get('upgrade_cost')
            tier = self.confirmed_metrics.get('tavern_tier')
            reserve=0 if obs.board_count==7 else self.config.min_gold_after_upgrade
            can_upgrade=(gold is not None and cost is not None and tier is not None and 1<=tier<6
                         and cost<=self.config.upgrade_max_cost and gold-cost>=reserve)
            if can_upgrade and (tier>=4 or obs.board_count==7) and not self.hand_probe:
                return self.action('click',f'升级酒馆 {tier}→{tier+1}',obs,'upgrade')
            if (self.config.auto_sell_for_space and obs.board_count==7 and not self.sold_for_space and not self.hand_probe
                    and gold is not None and gold>=2 and obs.shop_minions and len(obs.hand_minions)<8
                    and 'tavernkeeper' in obs.targets and 'friendly_target' in obs.targets):
                obs.targets['sell_minion']=obs.targets['friendly_target']
                return self.action('drag','卖出最左随从，为购买随从腾位',obs,'sell_minion','tavernkeeper')
            if self.config.inspect_hand_cards:
                if self.hand_probe:
                    point=tuple(self.hand_probe['point'])
                    if self.hand_probe.get('stage')=='inspect':
                        kind=obs.metrics.get('hand_card_kind','unknown')
                        if kind=='unknown' and self.clock()-self.hand_probe['since']<4:
                            return None
                        self.hand_probe['kind']=kind
                        obs.targets['clear_tooltip']=(.97,.35)
                        return self.action('hover','收起手牌说明并重新确认场面',obs,'clear_tooltip')
                    kind=self.hand_probe.get('kind','unknown')
                    if self.hand_probe.get('source')=='shop':
                        name=self.hand_probe['name']
                        present=any(abs(obs.targets[n][0]-point[0])<.025 for n in obs.shop_spells)
                        spell_cost=self.confirmed_metrics.get(name+'_cost')
                        if present and spell_cost is None and self.clock()-self.hand_probe.get('ready_since',0)<4:
                            return None
                        if (kind in ('buff','steal','targeted_acquire') or kind=='unknown' and spell_cost is not None and spell_cost<=3) and present and gold is not None and spell_cost is not None and gold>=spell_cost:
                            obs.targets['inspected_shop_spell']=point
                            return self.action('drag','测试：购买一张法术用于手牌识别',obs,'inspected_shop_spell','hand_drop')
                        self.shop_spell_skipped.add(point);self.hand_probe=None
                        return None
                    marked=self.hand_probe.get('mark') is not None
                    candidate=self.inspected_hand_candidate(obs) if marked else None
                    present=(candidate is not None if marked else
                             any(abs(obs.targets[n][0]-point[0])<.025 and abs(obs.targets[n][1]-point[1])<.025 for n in obs.hand_minions))
                    if marked and present and self.hand_probe.get('ready_frames',0)<2:
                        return None
                    if marked and not present and self.clock()-self.hand_probe.get('ready_since',0)<6:
                        return None
                    same_card=present and (self.hand_probe.get('ready_frames',0)>=2 if marked else len(obs.hand_minions)==self.hand_probe['count'])
                    if kind in ('coin','discover','buff','minion','steal','targeted_acquire') and same_card:
                        if marked:point=tuple(obs.targets[candidate])
                        obs.targets['inspected_hand']=point
                        if marked:obs.hand_marks['inspected_hand']=obs.hand_marks[candidate]
                        if kind=='minion' and (obs.board_count is None or obs.board_count>=7):
                            if (self.config.auto_sell_for_space and obs.board_count==7 and not self.sold_for_space
                                    and gold is not None and 'tavernkeeper' in obs.targets and 'friendly_target' in obs.targets):
                                obs.targets['sell_minion']=obs.targets['friendly_target']
                                return self.action('drag','卖出最左随从，为已识别随从腾位',obs,'sell_minion','tavernkeeper')
                            self.hand_skipped.add(point);self.hand_probe=None
                        elif kind=='buff' and (not obs.board_count or 'friendly_target' not in obs.targets):
                            self.hand_skipped.add(point);self.hand_probe=None
                        elif kind=='targeted_acquire' and not (obs.board_count and 'friendly_target' in obs.targets or obs.shop_minions):
                            self.hand_skipped.add(point);self.hand_probe=None
                        else:
                            obs.metrics['precast_hand_count']=len(obs.hand_minions)
                            obs.metrics['precast_hand_kind']=kind
                            obs.metrics['precast_board_count']=obs.board_count
                            if kind=='targeted_acquire':
                                destination='friendly_target' if obs.board_count and 'friendly_target' in obs.targets else obs.shop_minions[0]
                            else:
                                destination='friendly_target' if kind=='buff' else 'board_drop'
                            return self.action('drag',f'使用已读说明的手牌：{kind}',obs,'inspected_hand',destination)
                    else:
                        message='手牌图像或位置已变化，取消旧位置出牌' if marked and kind!='unknown' else '未可靠读到手牌类型，本回合跳过该牌'
                        self.log.emit(message,'WARNING',point=point)
                        self.hand_skipped.add(point);self.hand_probe=None
                names=obs.hand_minions
                if obs.hand_marks:
                    preferred=[n for n in obs.hand_priority if n in names]
                    ordered=preferred+[n for n in names if n not in preferred]
                    budget=max(3,min(10,len(names)))
                else:
                    offset=self.probe_cursor%len(names) if names else 0
                    ordered=names[offset:]+names[:offset]
                    budget=3
                for name in ordered:
                    point=tuple(obs.targets[name])
                    skipped=(any(abs(point[0]-p[0])<.015 and abs(point[1]-p[1])<.015 for p in self.hand_skipped)
                             if obs.hand_marks else point in self.hand_skipped)
                    if not skipped and self.probes_this_turn<budget:
                        return self.action('hover','读取手牌说明',obs,name)
                if self.config.test_shop_spells and not self.shop_spell_bought and obs.board_count and obs.board_count>=3:
                    for name in obs.shop_spells:
                        point=tuple(obs.targets[name]);spell_cost=self.confirmed_metrics.get(name+'_cost')
                        if point not in self.shop_spell_skipped and gold is not None and spell_cost is not None and gold>=spell_cost:
                            return self.action('hover','测试：读取商店法术说明',obs,name)
            # Upgrading needs no board slot. In particular, unknown board
            # occupancy or a full board must not block levels 4 -> 5 -> 6.
            if can_upgrade:
                return self.action('click',f'升级酒馆 {tier}→{tier+1}',obs,'upgrade')
            if obs.board_count is None:
                gold=self.confirmed_metrics.get('gold')
                if not obs.hand_minions and (gold is None or gold<3):
                    self.board_unknown_since=None
                    return None
                if self.board_unknown_since is None:
                    self.board_unknown_since=self.clock()
                    self.board_unknown_warned=False
                if self.clock()-self.board_unknown_since > 20:
                    # Skip uncertain recruit input, but keep observing combat and
                    # settlement so a tooltip cannot suspend the whole match.
                    if not self.board_unknown_warned:
                        self.log.emit('无法确认场面空位，暂不操作并继续观察阶段变化','WARNING')
                        self.board_unknown_warned=True
                return None
            self.board_unknown_since=None
            if not self.config.inspect_hand_cards and obs.hand_minions and obs.board_count < 7:
                return self.action('drag','将已识别随从打到场上',obs,obs.hand_minions[0],'board_drop')
            if gold is None:
                return None
            if gold >= 3 and obs.shop_minions and obs.board_count < 7 and len(obs.hand_minions) < 8:
                return self.action('drag','购买已识别随从',obs,obs.shop_minions[0],'hand_drop')
        if self.clock()-self.state_since > self.config.state_timeout and obs.state not in (State.RECRUIT,State.COMBAT):
            raise NeedsAttention(f'{obs.state.value} 状态等待超时')
        return None

    def sent(self, action, obs):
        self.last_action_time = self.clock()
        if action.kind=='hover':
            if action.target=='clear_tooltip':
                self.hand_probe['stage']='ready'
                self.hand_probe['ready_since']=self.clock()
            else:
                self.hand_probe={'point':tuple(obs.targets[action.target]),'since':self.clock(),'count':len(obs.hand_minions),'stage':'inspect',
                                 'source':'shop' if action.target.startswith('spell_shop_') else 'hand','name':action.target,
                                 'mark':obs.hand_marks.get(action.target),'ready_frames':0}
                if not action.target.startswith('spell_shop_'):
                    self.probes_this_turn+=1
                    self.probe_cursor+=1
            self.last_action=None
            self.log.emit('已发送操作：'+action.label,kind=action.kind,target=action.target)
            return
        self.last_action, self.last_signature = action, self.signature(obs)
        self.before_action = obs
        if self.recovery:
            if action.kind=='key' and action.key=='Escape':
                self.recovery['escapes']+=1
                self.recovery['last_sent']=self.clock()
            elif action.target=='concede':
                self.recovery['concede_attempts']+=1
                self.recovery['last_sent']=self.clock()
                self.recovery['stage']='wait_confirm'
                if not self.concede_sent:
                    self.recovery_streak+=1
                self.concede_sent=True
                self.match.end_reason='auto_recovery'
                self.store.save(self.match)
            elif action.target=='confirm_concede':
                self.recovery['confirm_attempts']+=1
                self.recovery['last_sent']=self.clock()
                self.recovery['stage']='wait_result'
        if action.target=='inspected_hand':
            self.hand_probe=None
            self.pending_hand_play={k:obs.metrics.get(k) for k in ('precast_hand_count','precast_hand_kind','precast_board_count')}
            self.pending_hand_play['card_mark']=obs.hand_marks.get('inspected_hand')
            if obs.metrics.get('precast_hand_kind') in TARGETED_HAND_KINDS:
                self.target_pending_since=self.clock()
        if action.target=='inspected_shop_spell':
            self.hand_probe=None
            self.shop_spell_bought=True
        if action.source_state==State.CHOICE:
            self.target_pending_since=self.clock() if obs.metrics.get('choice_targeted') else None
            if self.pending_hand_play and obs.metrics.get('choice_targeted'):
                self.pending_hand_play['target_expected']=True
        if action.target in ('friendly_target','shop_spell_target'):
            self.target_pending_since=None
            if self.pending_hand_play:
                self.pending_hand_play['target_clicked']=True
        if action.target=='sell_minion':
            self.sold_for_space=True
        if action.source_state == State.HERO and action.target in ('hero_2','hero_3'):
            self.hero_clicked = int(action.target[-1])
            if self.match:
                self.match.hero_slot = self.hero_clicked
                self.store.save(self.match)
        if action.source_state == State.MENU and action.target == 'concede' and self.match and not self.recovery:
            self.concede_sent=True
            self.match.end_reason = 'test_concede'
            self.store.save(self.match)
        if action.source_state == State.RECRUIT:
            self.turn_actions += 1
        self.log.emit('已发送操作：'+action.label, kind=action.kind, target=action.target)

    def interrupt(self):
        if self.match and not self.match.ended_at:
            self.match.ended_at = now_iso()
            if self.match.end_reason=='normal':
                self.match.end_reason = 'interrupted'
            self.match.result_status = 'interrupted'
            self.store.save(self.match)

import csv
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QTimer, QThread
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QTabWidget, QLineEdit, QCheckBox, QSpinBox, QDoubleSpinBox,
    QComboBox, QFormLayout, QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QMessageBox, QSplitter, QScrollArea, QFrame, QAbstractItemView,
)

from . import __version__
from .config import Config, Profile, project_root
from .model import State, STATE_NAMES
from .runner import Runner
from .store import Store
from .vision import Vision, crop


STYLE = '''
QWidget { color: #dce5ed; background: #10171f; font-family: "Microsoft YaHei"; font-size: 13px; }
QMainWindow { background: #10171f; }
QLabel { background: transparent; }
QLabel#title { font-size: 24px; font-weight: 700; color: #edf5fa; }
QLabel#subtitle { color: #8397a8; font-size: 12px; }
QLabel#sectionTitle { font-size: 14px; font-weight: 600; color: #dce5ed; }
QLabel#badge { background: #1b3235; color: #8bd3c3; padding: 6px 11px; border-radius: 6px; font-size: 11px; }
QLabel#metric { font-size: 25px; font-weight: 600; color: #edf5fa; }
QLabel#statusMetric { font-size: 18px; font-weight: 600; color: #8bd3c3; }
QFrame#card { background: #18232d; border: 1px solid #293b48; border-radius: 10px; }
QGroupBox { background: #18232d; border: 1px solid #293b48; border-radius: 9px; margin-top: 12px; padding: 9px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #a6bac9; }
QPushButton { background: #243541; border: 1px solid #354e5e; border-radius: 6px; padding: 6px 14px; min-height: 19px; }
QPushButton:hover { background: #304956; border-color: #588477; }
QPushButton:pressed { background: #1b2d35; }
QPushButton#primary { color: #102d29; background: #80cbb8; border: 1px solid #80cbb8; font-weight: 600; }
QPushButton#primary:hover { background: #9edeca; }
QPushButton#stop { color: #e4a99f; border-color: #704c48; }
QPushButton:disabled,QPushButton#primary:disabled,QPushButton#stop:disabled { color: #556a79; background: #182630; border-color: #283a47; }
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox { background: #111b24; border: 1px solid #314653; border-radius: 5px; padding: 6px 8px; selection-background-color: #346b68; }
QLineEdit:focus,QComboBox:focus,QSpinBox:focus,QDoubleSpinBox:focus { border-color: #74bcac; }
QPlainTextEdit,QTableWidget { background: #111b24; border: 1px solid #293d4a; border-radius: 6px; selection-background-color: #2a514f; selection-color: #e8faf4; }
QPlainTextEdit { padding: 7px; }
QTableWidget { alternate-background-color: #17252f; }
QTableWidget::item { padding: 5px 8px; border-bottom: 1px solid #20333f; }
QHeaderView::section { background: #21333f; border: none; border-bottom: 1px solid #314956; padding: 7px 8px; color: #a7bdcc; font-weight: 600; }
QTabWidget::pane { border: none; padding-top: 8px; }
QTabBar::tab { padding: 9px 20px; color: #8397a8; border-bottom: 2px solid #23333f; }
QTabBar::tab:hover { color: #dce5ed; }
QTabBar::tab:selected { color: #91d8c6; border-bottom: 2px solid #80cbb8; }
QSplitter::handle { background: #10171f; width: 10px; }
QScrollArea { border: none; }
QCheckBox { spacing: 9px; background: transparent; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #496473; border-radius: 4px; background: #101b24; }
QCheckBox::indicator:checked { background: #80cbb8; border: 1px solid #80cbb8; image: url("__CHECK_ICON__"); }
QScrollBar:vertical { background: #13202a; width: 9px; margin: 3px 0; border: none; }
QScrollBar::handle:vertical { background: #3a5362; min-height: 24px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #568277; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { background: #243a46; color: #edf5fa; border: 1px solid #4b6978; padding: 6px; }
'''.replace('__CHECK_ICON__',(project_root()/'assets'/'ui'/'check.svg').as_posix())

POINT_LABELS = {
    'launcher_play':'战网：进入游戏按钮','entry_continue':'游戏入口：点击进入',
    'main_modes':'主菜单：模式入口','mode_battlegrounds':'模式页：酒馆战棋',
    'lobby_play':'大厅：开始','hero_2':'英雄：中间左侧','hero_3':'英雄：中间右侧',
    'hero_confirm':'英雄：确认','upgrade':'酒馆：升级按钮','hand_drop':'买牌：手牌落点',
    'board_drop':'出牌：场地落点','result_continue':'结算：返回大厅',
    'concede':'Esc 菜单：认输','confirm_concede':'认输：确认','reconnect':'断线：重连',
    'choice_1':'发现：第一个可用选项',
    'choice_confirm':'局内选择：确认','tavernkeeper':'卖牌：酒馆老板头像',
}
REGION_LABELS = {'gold':'金币数字','upgrade_cost':'升级费用数字','tavern_tier':'当前酒馆等级',
                 'placement':'结算名次','rating_lobby':'大厅总分','rating_result':'结算总分','hero_2_region':'中间左英雄卡槽','hero_3_region':'中间右英雄卡槽'}
MARKER_LABELS = {'hero_available':'英雄可选标志','hero_locked':'英雄锁定标志','hero_selected':'英雄选中高亮',
                 'minion':'随从标记（排除法术）','board_minion':'场地槽：有随从','board_empty':'场地槽：空位'}


def image_to_pixmap(frame):
    rgb = cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
    h,w = rgb.shape[:2]
    return QPixmap.fromImage(QImage(rgb.data,w,h,rgb.strides[0],QImage.Format.Format_RGB888).copy())


class Canvas(QWidget):
    selected = Signal(object)

    def __init__(self, editable=False):
        super().__init__()
        self.setMinimumSize(430,260)
        self.frame = self.pixmap = None
        self.editable,self.point_mode = editable,False
        self.start=self.end=None
        self.image_rect=QRectF()

    def set_frame(self, frame):
        self.frame=frame.copy()
        self.pixmap=image_to_pixmap(frame)
        self.start=self.end=None
        self.update()

    def paintEvent(self, event):
        painter=QPainter(self)
        painter.fillRect(self.rect(),QColor('#0d141b'))
        if self.pixmap is None:
            painter.setPen(QColor('#748491'))
            painter.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,'等待客户区画面\n\n首次使用请先完成截图校准')
            return
        size=self.pixmap.size()
        scale=min(self.width()/size.width(),self.height()/size.height())
        w,h=size.width()*scale,size.height()*scale
        self.image_rect=QRectF((self.width()-w)/2,(self.height()-h)/2,w,h)
        painter.drawPixmap(self.image_rect,self.pixmap,QRectF(self.pixmap.rect()))
        if self.start is not None and self.end is not None:
            painter.setPen(QPen(QColor('#82c5a8'),2))
            if self.point_mode:
                painter.drawEllipse(self.end,6,6)
            else:
                painter.drawRect(QRectF(self.start,self.end).normalized())

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and self.editable and self.pixmap is not None and self.image_rect.contains(event.position()):
            self.start=self.end=event.position()
            self.update()

    def mouseMoveEvent(self,event):
        if self.editable and self.start is not None and event.buttons()&Qt.MouseButton.LeftButton:
            self.end=QPointF(max(self.image_rect.left(),min(self.image_rect.right(),event.position().x())),
                            max(self.image_rect.top(),min(self.image_rect.bottom(),event.position().y())))
            self.update()

    def mouseReleaseEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton or not self.editable or self.start is None:
            return
        r=self.image_rect
        # The release may arrive without an intermediate mouse-move event.
        self.end=QPointF(max(r.left(),min(r.right(),event.position().x())),
                        max(r.top(),min(r.bottom(),event.position().y())))
        if self.point_mode:
            self.selected.emit([(self.end.x()-r.x())/r.width(),(self.end.y()-r.y())/r.height()])
        else:
            selected=QRectF(self.start,self.end).normalized()
            if selected.width()>3 and selected.height()>3:
                self.selected.emit([(selected.x()-r.x())/r.width(),(selected.y()-r.y())/r.height(),selected.width()/r.width(),selected.height()/r.height()])
        self.update()


class AnalysisThread(QThread):
    result=Signal(str)

    def __init__(self,frame,profile,root,kind):
        super().__init__()
        self.frame,self.profile,self.root,self.kind=frame,profile,root,kind

    def run(self):
        try:
            obs=Vision(self.profile,self.root).analyze(self.frame,self.kind)
            self.result.emit(json.dumps(dict(state=STATE_NAMES[obs.state],confidence=obs.confidence,trusted=obs.trusted,
                                            metrics=obs.metrics,available_heroes=obs.available_heroes,board_count=obs.board_count,
                                            shop_minions=obs.shop_minions,hand_minions=obs.hand_minions,text=obs.evidence),ensure_ascii=False,indent=2))
        except Exception as e:
            self.result.emit(f'识别失败：{type(e).__name__}: {e}')


class CaptureThread(QThread):
    result=Signal(object)
    error=Signal(str)

    def __init__(self,kind):
        super().__init__()
        self.kind=kind

    def run(self):
        import threading
        from .windows import WindowsBackend,find_windows,user32
        backend=None
        try:
            candidates=[w for w in find_windows() if w.kind==self.kind]
            if not candidates:
                raise ValueError('未找到'+('炉石游戏' if self.kind=='game' else '战网')+'窗口，请确认程序已打开，或切换客户区类型')
            focused=[w for w in candidates if w.hwnd==user32.GetForegroundWindow()]
            if len(candidates)>1 and len(focused)!=1:
                raise ValueError('同类型目标窗口不止一个，请先将要采集的窗口置于前台')
            target=focused[0] if focused else candidates[0]
            target.activate()
            # Foreground ownership changes before Windows finishes its restore animation.
            # Capturing immediately can include the previous desktop under the new bounds.
            time.sleep(.45)
            backend=WindowsBackend(threading.Event(),threading.Event())
            frame,_=backend.screenshot(target)
            self.result.emit((frame,target.kind))
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if backend:
                backend.close()


class MainWindow(QMainWindow):
    def __init__(self,root=None,config_path=None):
        super().__init__()
        self.root=Path(root or project_root())
        self.worker=self.analysis=self.capture_thread=None
        self.pending_selection=None
        self.config_path=Path(config_path) if config_path else self.root/'data'/'settings.json'
        self.startup_error=''
        try:
            self.config=Config.load(self.config_path)
            self.profile=Profile.load(self.root/self.config.profile_path)
        except Exception as e:
            self.config,self.profile=Config(),Profile()
            self.startup_error=f'配置读取失败：{e}'
        self.setWindowTitle(f'酒馆助手 · HearthstoneBGA {__version__}')
        available=QApplication.primaryScreen().availableGeometry()
        self.resize(min(1180,available.width()-40),min(800,available.height()-48))
        self.setMinimumSize(940,700)
        central=QWidget()
        self.setCentralWidget(central)
        layout=QVBoxLayout(central)
        layout.setContentsMargins(20,14,20,12);layout.setSpacing(10)
        header=QHBoxLayout()
        titles=QVBoxLayout()
        title=QLabel('酒馆助手')
        title.setObjectName('title')
        subtitle=QLabel('BATTLEGROUNDS  /  自动对局 · 状态监控 · 对局记录')
        subtitle.setObjectName('subtitle')
        titles.addWidget(title);titles.addWidget(subtitle)
        header.addLayout(titles);header.addStretch()
        badge=QLabel('开发测试版 · 基础流程已实测')
        badge.setObjectName('badge');header.addWidget(badge,alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(header)
        self.tabs=QTabWidget();layout.addWidget(self.tabs)
        self.build_run_page();self.build_calibration_page();self.build_settings_page()
        footer=QLabel('F8 暂停    /    F9 停止    ·    仅操作前台目标窗口')
        footer.setToolTip(f'项目数据保存在 {self.root}')
        footer.setObjectName('subtitle');layout.addWidget(footer)
        self.refresh_history()
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh_history);self.timer.start(2500)
        if self.startup_error:
            self.log.appendPlainText(self.startup_error)

    def build_run_page(self):
        page=QWidget();self.tabs.addTab(page,'运行概览')
        layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0);layout.setSpacing(12)
        metrics=QHBoxLayout()
        self.state_label=QLabel('尚未启动')
        self.count_label=QLabel('0 局')
        self.rating_label=QLabel('—')
        for title,label in [('当前状态',self.state_label),('本次完成',self.count_label),('最近分数变化',self.rating_label)]:
            group=QFrame();group.setObjectName('card');box=QVBoxLayout(group)
            box.setContentsMargins(14,10,14,10);box.setSpacing(5)
            caption=QLabel(title);caption.setObjectName('subtitle');box.addWidget(caption)
            label.setObjectName('statusMetric' if label is self.state_label else 'metric')
            label.setWordWrap(True);box.addWidget(label)
            metrics.addWidget(group,2 if label is self.state_label else 1)
        layout.addLayout(metrics)
        controls=QHBoxLayout()
        self.start_button=QPushButton('启动');self.start_button.setObjectName('primary')
        self.pause_button=QPushButton('暂停');self.resume_button=QPushButton('继续')
        self.stop_button=QPushButton('停止');self.stop_button.setObjectName('stop')
        for button in [self.start_button,self.pause_button,self.resume_button,self.stop_button]:
            button.setMinimumWidth(80)
            controls.addWidget(button)
        controls.addStretch()
        self.mode_label=QLabel('只观察画面' if self.config.observe_only else '真实鼠标键盘操作');controls.addWidget(self.mode_label)
        layout.addLayout(controls)
        self.start_button.clicked.connect(self.start_run)
        self.pause_button.clicked.connect(self.pause_run)
        self.resume_button.clicked.connect(self.resume_run)
        self.stop_button.clicked.connect(self.stop_run)
        self.set_running(False)
        split=QSplitter(Qt.Orientation.Horizontal);split.setHandleWidth(12)
        preview_group=QGroupBox('当前客户区画面');preview_layout=QVBoxLayout(preview_group)
        self.preview=Canvas();self.preview.setMinimumHeight(210);preview_layout.addWidget(self.preview)
        split.addWidget(preview_group)
        log_group=QGroupBox('运行日志');log_layout=QVBoxLayout(log_group)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(2000)
        self.log.appendPlainText('开发测试版已就绪。当前配置：'+self.config.profile_path+'。\n启动前请核对运行设置；真实操作使用已有校准，切换分辨率后应重新验证。')
        log_layout.addWidget(self.log);split.addWidget(log_group);split.setSizes([680,420])
        layout.addWidget(split,3)
        group=QFrame();group.setObjectName('card');history_layout=QVBoxLayout(group)
        history_layout.setContentsMargins(12,10,12,12);history_layout.setSpacing(8)
        row=QHBoxLayout();heading=QLabel('对局记录');heading.setObjectName('sectionTitle')
        row.addWidget(heading);row.addStretch()
        export=QPushButton('导出 CSV');export.clicked.connect(self.export_history);row.addWidget(export)
        history_layout.addLayout(row)
        self.table=QTableWidget(0,7)
        self.table.setObjectName('historyTable')
        self.table.setHorizontalHeaderLabels(['开始时间','名次','结算分数','分差','结束原因','读取状态','英雄位置'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.horizontalHeader().setFixedHeight(36)
        self.table.verticalHeader().hide();self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False);self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(138);self.table.setMaximumHeight(220)
        history_layout.addWidget(self.table)
        layout.addWidget(group,2)

    def build_settings_page(self):
        page=QWidget();self.tabs.addTab(page,'运行设置')
        outer=QVBoxLayout(page);outer.setContentsMargins(0,0,0,0);outer.setSpacing(12)
        scroll=QScrollArea();scroll.setWidgetResizable(True);outer.addWidget(scroll)
        content=QWidget();scroll.setWidget(content);grid=QGridLayout(content)
        grid.setContentsMargins(0,0,8,0);grid.setHorizontalSpacing(16);grid.setVerticalSpacing(12)
        grid.setColumnStretch(0,1);grid.setColumnStretch(1,1)
        connection=QGroupBox('客户端');form=QFormLayout(connection);grid.addWidget(connection,0,0,1,2)
        self.controls={}
        self.path_edit=QLineEdit(self.config.battle_net_path)
        self.path_edit.setPlaceholderText('自动检测战网安装路径，或手动选择')
        pathrow=QHBoxLayout();pathrow.addWidget(self.path_edit)
        detect=QPushButton('自动检测');detect.clicked.connect(self.detect_launcher);pathrow.addWidget(detect)
        browse=QPushButton('选择…');pathrow.addWidget(browse);browse.clicked.connect(self.browse_exe)
        form.addRow('战网启动程序',pathrow)
        self.path_hint=QLabel();self.path_hint.setObjectName('subtitle');form.addRow('',self.path_hint)
        self.detect_launcher()
        entries=[
            ('observe_only','只观察画面，不发送鼠标键盘输入','check'),
            ('auto_launch','未运行时自动启动战网','check'),
            ('focus_on_start','运行时激活战网 / 游戏窗口','check'),
            ('recover_focus','失去前台后等待键鼠空闲 2 秒自动恢复（F8 暂停）','check'),
            ('auto_adapt_resolution','自动适配分辨率：必要时调整游戏窗口比例与位置','check'),
            ('inspect_hand_cards','读取手牌说明后区分随从与法术（测试功能）','check'),
            ('test_shop_spells','测试：每回合最多购买一张低费酒馆法术，读到明确效果后再用','check'),
            ('auto_sell_for_space','满场时为已识别手牌或可购买随从卖出腾位（最左，每回合最多一次）','check'),
            ('test_concede','测试模式：招募阶段到时主动认输','check'),
            ('poll_seconds','识别间隔（秒）','float',.3,30),
            ('action_seconds','动作最小间隔（秒）','float',.3,30),
            ('stable_frames','状态稳定帧数','int',2,10),
            ('state_timeout','未知 / 加载超时（秒）','float',15,1800),
            ('max_matches','最多完成局数（0 为不限）','int',0,1000),
            ('preferred_hero','中间英雄偏好（2 或 3）','int',2,3),
            ('upgrade_max_cost','允许升级的最高费用','int',0,30),
            ('min_gold_after_upgrade','升级后至少保留金币','int',0,30),
            ('max_actions_per_turn','每回合动作上限','int',1,100),
            ('concede_after_seconds','测试认输等待（秒）','float',5,1800),
        ]
        forms={}
        for i,title in enumerate(['运行与窗口','购买与出牌','识别与等待','测试选项']):
            group=QGroupBox(title);section=QFormLayout(group)
            section.setVerticalSpacing(12);section.setHorizontalSpacing(14)
            section.setFormAlignment(Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignLeft)
            section.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            grid.addWidget(group,1+i//2,i%2,alignment=Qt.AlignmentFlag.AlignTop if i>=2 else Qt.AlignmentFlag(0));forms[title]=section
        categories={
            '运行与窗口':['observe_only','auto_launch','focus_on_start','recover_focus','auto_adapt_resolution','max_matches','preferred_hero'],
            '购买与出牌':['inspect_hand_cards','test_shop_spells','auto_sell_for_space','upgrade_max_cost','min_gold_after_upgrade','max_actions_per_turn'],
            '识别与等待':['poll_seconds','action_seconds','stable_frames','state_timeout'],
            '测试选项':['test_concede','concede_after_seconds'],
        }
        short_labels={'observe_only':'只观察画面，不发送操作','auto_launch':'自动启动战网',
                      'focus_on_start':'启动时激活目标窗口','recover_focus':'失焦后自动恢复前台（空闲 2 秒）',
                      'auto_adapt_resolution':'自动适配分辨率与窗口比例',
                      'inspect_hand_cards':'读取手牌，区分随从与法术',
                      'test_shop_spells':'测试购买低费酒馆法术','auto_sell_for_space':'满场自动卖出腾位（最左随从）',
                      'test_concede':'测试中主动认输'}
        for key,label,kind,*limits in entries:
            form=forms[next(name for name,keys in categories.items() if key in keys)]
            if kind=='check':
                widget=QCheckBox(short_labels.get(key,label));widget.setToolTip(label)
                widget.setChecked(getattr(self.config,key));form.addRow(widget)
            else:
                widget=QDoubleSpinBox() if kind=='float' else QSpinBox()
                widget.setRange(*limits);widget.setValue(getattr(self.config,key))
                widget.setMaximumWidth(140);widget.setAlignment(Qt.AlignmentFlag.AlignRight)
                form.addRow(label,widget)
            self.controls[key]=widget
        for section in forms.values():
            for row in range(section.rowCount()):
                item=section.itemAt(row,QFormLayout.ItemRole.LabelRole)
                if item and item.widget():item.widget().setMinimumWidth(170)
        grid.setRowStretch(3,1)
        actions=QHBoxLayout()
        notice=QLabel('首次真实运行前需完成界面校准。缺少可靠识别证据时，程序会暂停并提示原因。\n测试认输对局会单独标记；读不到的名次或分数保留为空。')
        notice.setWordWrap(True);notice.setObjectName('subtitle');actions.addWidget(notice,1)
        save=QPushButton('保存设置');save.setObjectName('primary');save.setMinimumWidth(110)
        save.clicked.connect(self.save_settings);actions.addWidget(save);outer.addLayout(actions)

    def build_calibration_page(self):
        page=QWidget();self.tabs.addTab(page,'界面校准')
        layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0);layout.setSpacing(12)
        tools=QHBoxLayout()
        load=QPushButton('导入客户区截图');load.clicked.connect(self.load_frame);tools.addWidget(load)
        self.capture_button=QPushButton('3 秒后采集目标画面');self.capture_button.clicked.connect(self.capture_frame);tools.addWidget(self.capture_button)
        self.capture_timer=QTimer(self);self.capture_timer.setSingleShot(True);self.capture_timer.timeout.connect(self.begin_capture)
        self.frame_kind=QComboBox();self.frame_kind.addItem('炉石游戏客户区','game');self.frame_kind.addItem('战网客户区','launcher');tools.addWidget(self.frame_kind)
        tools.addStretch();layout.addLayout(tools)
        instruction=QLabel('坐标项：点击目标中心。区域与模板项：拖动框选。模板应选稳定、独特的局部，避开动画和英雄画像。')
        instruction.setWordWrap(True);instruction.setObjectName('subtitle');layout.addWidget(instruction)
        splitter=QSplitter(Qt.Orientation.Horizontal);splitter.setHandleWidth(12)
        self.canvas=Canvas(True);self.canvas.selected.connect(self.on_selection);splitter.addWidget(self.canvas)
        panel=QFrame();panel.setObjectName('card');panel.setMinimumWidth(300)
        side=QVBoxLayout(panel);side.setContentsMargins(14,14,14,14);side.setSpacing(10)
        caption=QLabel('校准目标');caption.setObjectName('sectionTitle');side.addWidget(caption)
        self.cal_kind=QComboBox();self.cal_kind.addItems(['操作坐标','数字 / 卡槽区域','状态模板','标记模板'])
        self.cal_name=QComboBox();side.addWidget(self.cal_kind);side.addWidget(self.cal_name)
        self.cal_kind.currentIndexChanged.connect(self.populate_calibration)
        self.cal_name.currentIndexChanged.connect(self.clear_selection)
        self.selection_label=QLabel('尚未选择');self.selection_label.setWordWrap(True);side.addWidget(self.selection_label)
        save=QPushButton('保存此校准项');save.clicked.connect(self.save_selection);side.addWidget(save)
        test=QPushButton('测试当前截图识别');test.clicked.connect(self.analyze_frame);side.addWidget(test)
        finish=QPushButton('检查并完成校准');finish.clicked.connect(self.finish_calibration);side.addWidget(finish)
        self.cal_summary=QLabel();self.cal_summary.setWordWrap(True);side.addWidget(self.cal_summary)
        caption=QLabel('识别结果与提示');caption.setObjectName('subtitle');side.addWidget(caption)
        self.analysis_text=QPlainTextEdit();self.analysis_text.setReadOnly(True);side.addWidget(self.analysis_text,1)
        splitter.addWidget(panel);splitter.setSizes([740,350]);layout.addWidget(splitter,1)
        self.populate_calibration();self.update_summary()

    def populate_calibration(self):
        self.pending_selection=None;self.cal_name.clear()
        kind=self.cal_kind.currentIndex()
        self.canvas.point_mode=kind==0
        if kind==0:
            for key in self.profile.points:
                label=POINT_LABELS.get(key,key.replace('shop_','商店槽 ').replace('hand_','手牌槽 '))
                self.cal_name.addItem(label,key)
        elif kind==1:
            for key in self.profile.regions:
                label=REGION_LABELS.get(key,key.replace('_region','').replace('shop_','商店槽区域 ').replace('hand_','手牌槽区域 ').replace('board_','场地槽区域 '))
                self.cal_name.addItem(label,key)
        elif kind==2:
            for state in State:
                if state not in (State.UNKNOWN,State.AUTH):
                    self.cal_name.addItem(STATE_NAMES[state],state.value)
        else:
            for key,label in MARKER_LABELS.items():
                self.cal_name.addItem(label,key)
        self.clear_selection()

    def clear_selection(self):
        self.pending_selection=None
        self.canvas.start=self.canvas.end=None;self.canvas.update()
        self.selection_label.setText('请在截图中点击或框选当前项目')

    def on_selection(self,selection):
        self.pending_selection=selection
        self.selection_label.setText('已选择：'+', '.join(f'{x:.4f}' for x in selection))

    def update_summary(self):
        self.cal_summary.setText(f'已确认坐标 {len(self.profile.verified_points)} 项；区域 {len(self.profile.verified_regions)} 项；状态模板 {len(self.profile.anchors)} 项。\n'+('已完成校准' if self.profile.calibrated else f'尚缺 {len(self.profile.missing())} 项'))

    def save_profile(self):
        self.profile.save(self.root/self.config.profile_path)
        self.update_summary()

    def save_selection(self):
        if self.canvas.frame is None or self.pending_selection is None:
            self.selection_label.setText('请先载入画面并选择目标');return
        key=self.cal_name.currentData();kind=self.cal_kind.currentIndex();selection=self.pending_selection
        if len(selection)!=(2 if kind==0 else 4):
            self.selection_label.setText('选择类型不匹配，请重新选择');return
        original=Profile(**json.loads(json.dumps(asdict(self.profile))))
        try:
            if kind==0:
                if not all(0<x<1 for x in selection):
                    raise ValueError('操作坐标必须在客户区内部，请避开最边缘')
                self.profile.points[key]=selection
                if key not in self.profile.verified_points:self.profile.verified_points.append(key)
            elif kind==1:
                self.profile.regions[key]=selection
                if key not in self.profile.verified_regions:self.profile.verified_regions.append(key)
            else:
                selected=crop(self.canvas.frame,selection)
                if selected.size==0 or selected.std()<5:
                    raise ValueError('模板过小或接近纯色，请选择独特的局部')
                directory=self.root/'profiles'/'templates';directory.mkdir(parents=True,exist_ok=True)
                filename=directory/f'{key}_{time.time_ns()}.png'
                ok,data=cv2.imencode('.png',selected)
                if not ok:raise ValueError('模板编码失败')
                data.tofile(filename)
                h,w=self.canvas.frame.shape[:2]
                spec=dict(file=filename.relative_to(self.root).as_posix(),box=selection,frame_size=[w,h],threshold=.92)
                (self.profile.anchors if kind==2 else self.profile.markers)[key]=spec
            if self.frame_kind.currentData()=='game':
                h,w=self.canvas.frame.shape[:2];self.profile.aspect_ratio=w/h
            self.profile.calibrated=False
            self.save_profile();self.selection_label.setText('已保存：'+self.cal_name.currentText())
        except Exception as e:
            self.profile=original;self.update_summary()
            QMessageBox.warning(self,'校准失败',str(e))

    def finish_calibration(self):
        missing=self.profile.missing()
        if missing:
            self.analysis_text.setPlainText('尚需完成以下校准项：\n'+'\n'.join(missing));return
        previous=self.profile.calibrated
        try:
            self.profile.calibrated=True;self.save_profile()
        except Exception as e:
            self.profile.calibrated=previous;self.update_summary()
            QMessageBox.warning(self,'校准未完成',str(e));return
        self.analysis_text.setPlainText('校准项已完整。建议先使用只观察模式验证不同画面，再启动真实操作。\n完整性检查不能代替真实对局验收。')

    def load_frame(self):
        filename,_=QFileDialog.getOpenFileName(self,'选择客户区截图',str(self.root),'图片 (*.png *.jpg *.jpeg *.bmp)')
        if filename:
            try:
                frame=cv2.imdecode(np.fromfile(filename,dtype=np.uint8),cv2.IMREAD_COLOR)
                if frame is None:raise ValueError('图片格式无法读取')
            except Exception as e:
                QMessageBox.warning(self,'无法载入',str(e));return
            self.canvas.set_frame(frame);self.clear_selection()
            self.analysis_text.setPlainText('已导入：'+filename+'\n请确认上方客户区类型与图片一致。')

    def capture_frame(self):
        if self.capture_timer.isActive() or (self.capture_thread and self.capture_thread.isRunning()):return
        self.capture_button.setEnabled(False);self.frame_kind.setEnabled(False)
        self.showMinimized()
        self.analysis_text.setPlainText('3 秒后将激活并采集所选类型的客户区，请勿遮挡目标窗口。')
        self.capture_timer.start(3000)

    def begin_capture(self):
        if self.capture_thread and self.capture_thread.isRunning():return
        self.capture_thread=CaptureThread(self.frame_kind.currentData())
        self.capture_thread.result.connect(self.captured)
        self.capture_thread.error.connect(self.capture_failed)
        self.capture_thread.finished.connect(self.capture_finished)
        self.capture_thread.start()

    def capture_finished(self):
        self.capture_button.setEnabled(True);self.frame_kind.setEnabled(True)

    def capture_failed(self,text):
        self.analysis_text.setPlainText('采集失败：'+text);self.showNormal()

    def captured(self,result):
        frame,kind=result
        self.canvas.set_frame(frame);self.frame_kind.setCurrentIndex(0 if kind=='game' else 1)
        h,w=frame.shape[:2]
        self.analysis_text.setPlainText(f'已采集'+('炉石游戏' if kind=='game' else '战网')+f'客户区：{w} × {h}。')
        self.clear_selection();self.showNormal()

    def analyze_frame(self):
        if self.canvas.frame is None:
            self.analysis_text.setPlainText('请先载入截图');return
        if self.analysis and self.analysis.isRunning():return
        self.analysis_text.setPlainText('正在本地初始化 OCR 并分析…')
        self.analysis=AnalysisThread(self.canvas.frame.copy(),Profile(**json.loads(json.dumps(asdict(self.profile)))),self.root,self.frame_kind.currentData())
        self.analysis.result.connect(self.analysis_text.setPlainText);self.analysis.start()

    def read_settings(self):
        values=asdict(self.config);values['battle_net_path']=self.path_edit.text().strip()
        for key,control in self.controls.items():
            values[key]=control.isChecked() if isinstance(control,QCheckBox) else control.value()
        config=Config(**values);config.validate();return config

    def save_settings(self):
        try:
            self.config=self.read_settings();self.config.save(self.config_path)
            self.mode_label.setText('只观察画面' if self.config.observe_only else '真实鼠标键盘操作')
            self.log.appendPlainText('设置已保存')
        except Exception as e:
            QMessageBox.warning(self,'设置未保存',str(e))

    def browse_exe(self):
        filename,_=QFileDialog.getOpenFileName(self,'选择战网启动程序',self.path_edit.text(),'程序 (*.exe)')
        if filename:self.path_edit.setText(filename)

    def detect_launcher(self):
        from .discovery import detect_battle_net
        path,source=detect_battle_net(self.path_edit.text().strip())
        if path:self.path_edit.setText(path)
        self.path_hint.setText(('已检测：' if path else '')+source)

    def set_running(self,running):
        self.start_button.setEnabled(not running)
        for button in [self.pause_button,self.resume_button,self.stop_button]:button.setEnabled(running)
        if hasattr(self,'tabs') and self.tabs.count()>=3:
            self.tabs.setTabEnabled(1,not running);self.tabs.setTabEnabled(2,not running)

    def start_run(self):
        if self.worker and self.worker.isRunning():return
        try:
            config=self.read_settings()
            if config.auto_launch:
                from .discovery import detect_battle_net
                detected,_=detect_battle_net(config.battle_net_path)
                if detected:
                    config.battle_net_path=detected;self.path_edit.setText(detected)
            profile=Profile.load(self.root/config.profile_path)
            if not config.observe_only and (not profile.calibrated or profile.missing()):
                raise ValueError('当前布局未完成校准，请先完成校准并验证识别')
            config.save(self.config_path);self.config=config
            self.worker=Runner(config,self.root)
            self.worker.message.connect(self.log.appendPlainText)
            self.worker.status.connect(self.state_label.setText)
            self.worker.preview.connect(self.preview.set_frame)
            self.worker.observation.connect(self.on_observation)
            self.worker.records_changed.connect(self.refresh_history)
            self.worker.finished.connect(self.run_finished)
            self.set_running(True)
            self.mode_label.setText('只观察画面' if config.observe_only else '真实操作 · F9 停止')
            self.state_label.setText('初始化中…')
            self.worker.start()
            self.showMinimized()
        except Exception as e:
            QMessageBox.warning(self,'无法启动',str(e))

    def run_finished(self):
        self.set_running(False)
        if not self.state_label.text().startswith('运行失败'):
            self.state_label.setText('本次运行已结束')
        self.showNormal()

    def pause_run(self):
        if self.worker:self.worker.pause()

    def resume_run(self):
        if self.worker and self.worker.isRunning():
            self.worker.resume();self.showMinimized()

    def stop_run(self):
        if self.worker:self.worker.stop()

    def on_observation(self,obs):
        self.count_label.setText(f'{obs["completed"]} 局')

    def refresh_history(self):
        path=self.root/'data'/'matches.sqlite3'
        if not path.exists():return
        try:
            store=Store(path)
            try:records=store.recent()
            finally:store.close()
            self.table.setRowCount(len(records))
            reasons={'normal':'正常结束','test_concede':'测试主动认输','interrupted':'已中断'}
            statuses={'in_progress':'进行中','attached_in_progress':'中途接入','awaiting_lobby':'等待大厅分数','complete':'读取完整','replayed_complete':'截图补读完整','partial':'部分字段未知','interrupted':'未完成'}
            from datetime import datetime, timezone, timedelta
            for row,record in enumerate(records):
                started=datetime.fromisoformat(record['started_at']).astimezone(timezone(timedelta(hours=8))).strftime('%m-%d %H:%M:%S')
                values=[started,record['placement'],record['rating_after'],record['rating_delta'],reasons.get(record['end_reason'],record['end_reason']),statuses.get(record['result_status'],record['result_status']),record['hero_slot']]
                for col,value in enumerate(values):
                    item=QTableWidgetItem('—' if value is None else str(value))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(row,col,item)
            if records:
                delta=records[0]['rating_delta'];self.rating_label.setText('—' if delta is None else f'{delta:+d}')
        except Exception as e:
            self.log.appendPlainText(f'读取记录失败：{e}')

    def export_history(self):
        filename,_=QFileDialog.getSaveFileName(self,'导出对局记录',str(self.root/'data'/'matches.csv'),'CSV (*.csv)')
        if not filename:return
        store=Store(self.root/'data'/'matches.sqlite3')
        try:
            records=store.recent(100000)
            if records:
                with open(filename,'w',encoding='utf-8-sig',newline='') as file:
                    writer=csv.DictWriter(file,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
            self.log.appendPlainText(f'已导出 {len(records)} 条记录')
        finally:store.close()

    def closeEvent(self,event):
        self.capture_timer.stop()
        # Wait without killing the thread or leaving a pressed mouse button.
        if self.worker and self.worker.isRunning():
            self.worker.stop();event.ignore()
            QTimer.singleShot(150,self.close)
            return
        for thread in [self.analysis,self.capture_thread]:
            if thread and thread.isRunning():
                event.ignore();QTimer.singleShot(150,self.close);return
        event.accept()


def main():
    app=QApplication(sys.argv)
    # Offscreen Qt does not always discover Windows' system font collection.
    # Load installed fonts without redistributing Microsoft's font files.
    import os
    for filename in ['msyh.ttc','msyhbd.ttc']:
        path=Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts'/filename
        if path.exists():QFontDatabase.addApplicationFont(str(path))
    app.setStyle('Fusion');app.setStyleSheet(STYLE)
    app.setFont(QFont('Microsoft YaHei',10))
    test_path=None
    if '--test-config' in sys.argv:
        test_path=(project_root()/sys.argv[sys.argv.index('--test-config')+1]).resolve()
        if not test_path.is_relative_to(project_root().resolve()):
            raise ValueError('测试配置必须位于项目内')
    window=MainWindow(config_path=test_path);window.show()
    if test_path:
        def start_test():
            window.start_run()
            if window.worker:
                window.worker.finished.connect(window.close)
        QTimer.singleShot(700,start_test)
    if '--smoke-test' in sys.argv:
        def save_preview():
            path=window.root/'data'/'gui-preview.png';path.parent.mkdir(parents=True,exist_ok=True)
            window.grab().save(str(path));window.close();app.quit()
        QTimer.singleShot(600,save_preview)
    return app.exec()

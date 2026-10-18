"""Packaged check of the physical-pixel adapter using an owned test window."""
from datetime import datetime
import json
from pathlib import Path
import sys
import threading
import time
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QLabel
from .config import project_root
from .windows import Window,WindowsBackend
from .discovery import detect_battle_net
from .gui import STYLE


def run_environment_qa():
    root=project_root()
    app=QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    widget=QWidget();widget.setWindowTitle('分辨率与战网路径自检')
    widget.resize(1000,650)
    layout=QVBoxLayout(widget);layout.addWidget(QLabel('正在验证物理像素、窗口比例及自动路径检测。\n此测试不会向游戏发送输入。'))
    widget.show();app.processEvents()
    backend=WindowsBackend(threading.Event(),threading.Event())
    target=Window(int(widget.winId()),widget.windowTitle(),sys.executable,'game')
    report={'time':datetime.now().astimezone().isoformat(),'frozen':bool(getattr(sys,'frozen',False)),
            'scope':'自有窗口适配与本机安装检测；不启动对局','passed':False}
    try:
        report['before']=target.rect()
        report['adapter']=target.adapt_resolution(16/9)
        app.processEvents();time.sleep(.2);target.activate()
        frame,rect=backend.screenshot(target)
        assert abs(rect[2]/rect[3]/(16/9)-1)<.01
        assert frame.shape[:2]==(rect[3],rect[2])
        assert not target.adapt_resolution(16/9)['changed']
        path,source=detect_battle_net()
        registry_path,registry_source=detect_battle_net('',running=[])
        assert path and registry_path,'未安装战网或未找到客户端'
        report.update(after=rect,battle_net_path=path,path_source=source,registry_path=registry_path,
                      registry_source=registry_source,repeat_no_change=True,passed=True)
    except Exception as e:report['error']=f'{type(e).__name__}: {e}'
    finally:
        backend.close();widget.close();app.processEvents()
        destination=root/'data'/'environment-selftest.json';destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['passed'] else 1

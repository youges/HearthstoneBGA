"""Exercise this application's real Qt controls without sending gameplay input."""
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from unittest.mock import patch

import cv2
import numpy as np
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton

from .config import Config, Profile, project_root
from .gui import MainWindow, STYLE


def run_calibration_qa(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    root=project_root()
    run_root=root/'data'/'calibration-qa'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    run_root.mkdir(parents=True)
    source=root/'profiles'/'pc-integration.json'
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    shutil.copytree(root/'profiles',run_root/'profiles')
    shutil.copytree(root/'assets',run_root/'assets')
    config=Config.load(root/'data'/'settings.json')
    config.profile_path='profiles/pc-integration.json'
    config.observe_only=True
    config.save(run_root/'data'/'settings.json')
    fixture=root/'data'/'calibration'/'targeting-success-20261017'/'settled.png'
    if not fixture.exists():
        raise FileNotFoundError('缺少真实对局客户区测试图片：'+str(fixture))
    app=QApplication.instance() or QApplication(sys.argv)
    app.setStyle('Fusion');app.setStyleSheet(STYLE)
    import os
    for filename in ['msyh.ttc','msyhbd.ttc']:
        font=Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts'/filename
        if font.exists():QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont('Microsoft YaHei',10))
    window=MainWindow(run_root);window.show();window.tabs.setCurrentIndex(1)
    QTest.qWait(350)
    report={'time':datetime.now().astimezone().isoformat(),'frozen':bool(getattr(sys,'frozen',False)),
            'scope':'真实 Qt 按钮、客户区截图采集和本地 OCR；不执行对局操作',
            'isolated_root':str(run_root),'checks':[],'screenshots':[], 'passed':False}

    def check(name,condition,detail=''):
        report['checks'].append({'name':name,'passed':bool(condition),'detail':detail})
        if not condition:raise AssertionError(name+': '+detail)

    def click(text):
        button=next(b for b in window.findChildren(QPushButton) if b.text()==text)
        check(text+'可用',button.isEnabled())
        QTest.mouseClick(button,Qt.MouseButton.LeftButton);QTest.qWait(80)

    def screenshot(name):
        window.showNormal();window.raise_();app.processEvents();QTest.qWait(120)
        path=output/(name+'.png')
        check('保存截图 '+name,window.grab().save(str(path)))
        report['screenshots'].append(str(path))

    def wait_until(predicate,seconds=30):
        deadline=time.monotonic()+seconds
        while not predicate() and time.monotonic()<deadline:
            app.processEvents();time.sleep(.02)
        check('异步操作完成',predicate())

    try:
        click('保存此校准项')
        check('空选择保护','请先载入' in window.selection_label.text())
        click('测试当前截图识别')
        check('无截图识别保护',window.analysis_text.toPlainText()=='请先载入截图')
        # Only automate the filename selection; image decoding and all button slots are real.
        with patch.object(QFileDialog,'getOpenFileName',return_value=(str(fixture),'图片')):
            click('导入客户区截图')
        check('中文路径图片导入',window.canvas.frame is not None)
        screenshot('导入客户区截图')
        original_frame=window.canvas.frame.copy()
        warnings=[]
        with patch.object(QFileDialog,'getOpenFileName',return_value=(str(run_root/'不存在.png'),'')), \
             patch.object(QMessageBox,'warning',side_effect=lambda *a:warnings.append(str(a[2]))):
            click('导入客户区截图')
        check('文件不存在时保留原截图',bool(warnings) and np.array_equal(original_frame,window.canvas.frame))
        for kind,key,suffix in [(0,'hero_2','操作坐标'),(1,'gold','区域'),(2,'recruit','状态模板'),(3,'minion','标记模板')]:
            window.cal_kind.setCurrentIndex(kind)
            window.cal_name.setCurrentIndex(window.cal_name.findData(key));app.processEvents()
            r=window.canvas.image_rect
            start=QPoint(round(r.x()+r.width()*.35),round(r.y()+r.height()*.3))
            end=QPoint(round(r.x()+r.width()*.46),round(r.y()+r.height()*.55))
            if kind==0:QTest.mouseClick(window.canvas,Qt.MouseButton.LeftButton,pos=start)
            else:
                # Deliberately omit move: a quick drag must still use the release position.
                QTest.mousePress(window.canvas,Qt.MouseButton.LeftButton,pos=start)
                QTest.mouseRelease(window.canvas,Qt.MouseButton.LeftButton,pos=end)
            check('选择 '+suffix,window.pending_selection is not None)
            click('保存此校准项')
            check('保存 '+suffix,window.selection_label.text().startswith('已保存'))
            persisted=Profile.load(run_root/config.profile_path)
            check('保存后可重新读取 '+suffix,not persisted.calibrated)
            screenshot('保存此校准项' if kind==0 else '保存此校准项-'+suffix)
            window.clear_selection()
            check('清除旧选框',window.canvas.start is None and window.pending_selection is None)
        window.profile=Profile.load(source)
        window.profile.calibrated=False;window.save_profile();window.update_summary()
        click('测试当前截图识别')
        wait_until(lambda:window.analysis is not None and not window.analysis.isRunning())
        QTest.qWait(150)
        analysis=window.analysis_text.toPlainText()
        parsed=json.loads(analysis)
        report['recognition']=parsed
        check('真实对局截图识别',parsed['state']=='招募阶段',analysis)
        screenshot('测试当前截图识别')
        saved_profile=window.profile
        window.profile=Profile();click('检查并完成校准')
        check('不完整校准拒绝完成','尚需完成' in window.analysis_text.toPlainText())
        screenshot('检查并完成校准-缺项提示')
        window.profile=saved_profile;click('检查并完成校准')
        check('完整校准写盘',Profile.load(run_root/config.profile_path).calibrated)
        screenshot('检查并完成校准')
        # Actual installed Battle.net window, actual three-second timer and capture worker.
        window.frame_kind.setCurrentIndex(1)
        started=time.monotonic();click('3 秒后采集目标画面')
        check('倒计时防止重复采集',not window.capture_button.isEnabled())
        wait_until(lambda:window.capture_thread is not None and not window.capture_thread.isRunning())
        QTest.qWait(200)
        check('真实战网客户区采集','已采集战网客户区' in window.analysis_text.toPlainText(),window.analysis_text.toPlainText())
        check('三秒延迟',time.monotonic()-started>=3)
        check('采集完成恢复按钮',window.capture_button.isEnabled() and window.frame_kind.isEnabled())
        ok,encoded=cv2.imencode('.png',window.canvas.frame)
        check('保存客户区原图',ok)
        encoded.tofile(output/'3 秒后采集目标画面-客户区原图.png')
        screenshot('3 秒后采集目标画面')
        report['passed']=True
    except Exception as e:
        report['error']=f'{type(e).__name__}: {e}'
        screenshot('测试失败现场')
    finally:
        for thread in [window.analysis,window.capture_thread]:
            if thread and thread.isRunning():
                while thread.isRunning():
                    app.processEvents();time.sleep(.02)
        window.close();app.processEvents()
        report['production_profile_unchanged']=before==hashlib.sha256(source.read_bytes()).hexdigest()
        report['passed']=report['passed'] and report['production_profile_unchanged']
        (output/'校准测试结果.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        shutil.copy2(output/'校准测试结果.json',run_root/'result.json')
    return 0 if report['passed'] else 1

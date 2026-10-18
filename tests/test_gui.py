import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QMessageBox
import numpy as np

from bga.gui import MainWindow,STYLE


def test_gui_opens_all_pages_and_saves_calibration_without_input(tmp_path):
    app=QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    window=MainWindow(tmp_path)
    try:
        window.show();app.processEvents()
        assert window.tabs.count()==3
        assert window.start_button.isEnabled()
        assert not window.stop_button.isEnabled()
        assert window.controls['observe_only'].isChecked()
        for i in range(3):
            window.tabs.setCurrentIndex(i);app.processEvents()
            assert window.grab().width()>900
        frame=np.random.default_rng(1).integers(0,255,(450,800,3),dtype=np.uint8)
        window.canvas.set_frame(frame)
        window.cal_kind.setCurrentIndex(0)
        window.cal_name.setCurrentIndex(window.cal_name.findData('hero_2'))
        window.on_selection([.4,.5]);window.save_selection()
        assert window.profile.points['hero_2']==[.4,.5]
        assert 'hero_2' in window.profile.verified_points
        assert not window.profile.calibrated
        window.finish_calibration()
        assert '尚需' in window.analysis_text.toPlainText()
        assert (tmp_path/'profiles'/'default.json').exists()
    finally:
        window.close();app.processEvents()


def test_fast_drag_uses_release_position_and_switch_clears_overlay(tmp_path):
    app=QApplication.instance() or QApplication([])
    window=MainWindow(tmp_path)
    try:
        window.show();window.tabs.setCurrentIndex(1)
        window.canvas.set_frame(np.zeros((450,800,3),np.uint8))
        window.cal_kind.setCurrentIndex(1);app.processEvents()
        r=window.canvas.image_rect
        start=QPoint(round(r.x()+r.width()*.2),round(r.y()+r.height()*.2))
        end=QPoint(round(r.x()+r.width()*.4),round(r.y()+r.height()*.5))
        QTest.mousePress(window.canvas,Qt.MouseButton.LeftButton,pos=start)
        QTest.mouseRelease(window.canvas,Qt.MouseButton.LeftButton,pos=end)
        assert window.pending_selection is not None
        assert abs(window.pending_selection[2]-.2)<.01
        assert abs(window.pending_selection[3]-.3)<.01
        window.cal_name.setCurrentIndex(1)
        assert window.pending_selection is None and window.canvas.start is None
    finally:
        window.close();app.processEvents()


def test_invalid_file_keeps_frame_and_save_failure_rolls_back(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    window=MainWindow(tmp_path)
    frame=np.zeros((450,800,3),np.uint8)
    warnings=[]
    monkeypatch.setattr(QMessageBox,'warning',lambda *args:warnings.append(args[2]))
    try:
        window.canvas.set_frame(frame)
        monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *args:(str(tmp_path/'missing.png'),''))
        window.load_frame()
        assert warnings and np.array_equal(window.canvas.frame,frame)
        window.cal_name.setCurrentIndex(window.cal_name.findData('hero_2'))
        original=window.profile.points['hero_2'][:]
        window.on_selection([.4,.5])
        def fail():raise OSError('磁盘写入失败')
        monkeypatch.setattr(window,'save_profile',fail)
        window.save_selection()
        assert window.profile.points['hero_2']==original
        assert 'hero_2' not in window.profile.verified_points
        assert warnings[-1]=='磁盘写入失败'
    finally:
        window.close();app.processEvents()


def test_capture_timer_prevents_duplicate_and_closing_cancels_it(tmp_path):
    app=QApplication.instance() or QApplication([])
    window=MainWindow(tmp_path)
    window.show()
    window.capture_frame()
    assert window.capture_timer.isActive()
    assert not window.capture_button.isEnabled()
    assert not window.frame_kind.isEnabled()
    window.close();app.processEvents()
    assert not window.capture_timer.isActive()
    assert window.capture_thread is None


def test_capture_respects_selected_client_kind(monkeypatch):
    from bga import windows
    from bga.gui import CaptureThread
    calls=[]
    class Target:
        def __init__(self,kind,hwnd):self.kind,self.hwnd=kind,hwnd
        def activate(self):calls.append(('activate',self.kind))
    class Backend:
        def __init__(self,*args):pass
        def screenshot(self,target):
            calls.append(('capture',target.kind))
            return np.zeros((300,400,3),np.uint8),(0,0,400,300)
        def close(self):calls.append(('close',))
    monkeypatch.setattr(windows,'find_windows',lambda:[Target('game',1),Target('launcher',2)])
    monkeypatch.setattr(windows.user32,'GetForegroundWindow',lambda:2)
    monkeypatch.setattr(windows,'WindowsBackend',Backend)
    thread=CaptureThread('launcher')
    results=[];thread.result.connect(results.append)
    thread.run()
    assert results[0][1]=='launcher'
    assert calls==[('activate','launcher'),('capture','launcher'),('close',)]
    monkeypatch.setattr(windows,'find_windows',lambda:[])
    errors=[];thread.error.connect(errors.append);thread.run()
    assert '未找到战网窗口' in errors[0]

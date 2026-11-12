import pytest
from PySide6.QtCore import Qt,QTime,QPoint,QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog

from bga.schedule_widgets import TimeInput,TimeDialog,TimeWheel


@pytest.mark.parametrize('text,expected',[('08:30','08:30'),('8:30','08:30'),('0:5','00:05'),('23:59','23:59'),('24:00',''),('12:60',''),('abc',''),('','')])
def test_time_text_is_editable_and_invalid_values_are_rejected(text,expected):
    app=QApplication.instance() or QApplication([]);widget=TimeInput(QTime(8,0))
    try:
        widget.edit.selectAll();QTest.keyClick(widget.edit,Qt.Key.Key_Backspace);QTest.keyClicks(widget.edit,text)
        assert widget.time().toString('HH:mm')==expected
        widget.normalize()
        if expected:assert widget.edit.text()==expected
    finally:widget.close();widget.deleteLater();app.processEvents()


def test_wheels_support_keyboard_scroll_drag_and_tap():
    app=QApplication.instance() or QApplication([]);wheel=TimeWheel(59,0);wheel.show();app.processEvents()
    try:
        QTest.keyClick(wheel,Qt.Key.Key_Up);assert wheel.value==59
        QTest.keyClick(wheel,Qt.Key.Key_Down);assert wheel.value==0
        event=QWheelEvent(QPointF(50,105),QPointF(50,105),QPoint(),QPoint(0,-120),
                          Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        QApplication.sendEvent(wheel,event);assert wheel.value==1
        QTest.mousePress(wheel,Qt.MouseButton.LeftButton,pos=QPoint(50,105))
        QTest.mouseMove(wheel,QPoint(50,63));QTest.mouseRelease(wheel,Qt.MouseButton.LeftButton,pos=QPoint(50,63))
        assert wheel.value==2
        QTest.mouseClick(wheel,Qt.MouseButton.LeftButton,pos=QPoint(50,147));assert wheel.value==3
    finally:wheel.close();wheel.deleteLater();app.processEvents()


def test_picker_confirm_updates_time_and_cancel_keeps_typed_value(monkeypatch):
    app=QApplication.instance() or QApplication([]);widget=TimeInput(QTime(8,30))
    def accept(dialog):
        assert dialog.time()==QTime(8,30)
        dialog.hours.step(7);dialog.minutes.step(15)
        return QDialog.DialogCode.Accepted
    try:
        monkeypatch.setattr(TimeDialog,'exec',accept);widget.choose()
        assert widget.edit.text()=='15:45'
        monkeypatch.setattr(TimeDialog,'exec',lambda dialog:QDialog.DialogCode.Rejected)
        widget.choose();assert widget.edit.text()=='15:45'
    finally:widget.close();widget.deleteLater();app.processEvents()

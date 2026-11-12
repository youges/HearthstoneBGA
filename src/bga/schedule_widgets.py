"""Editable time text and a touch-style hour/minute wheel picker."""
import re
from PySide6.QtCore import Qt, QTime, Signal
from PySide6.QtGui import QColor, QPainter, QFont
from PySide6.QtWidgets import (
    QWidget,QLineEdit,QPushButton,QHBoxLayout,QVBoxLayout,QDialog,QLabel,
    QDialogButtonBox,
)


class TimeWheel(QWidget):
    valueChanged=Signal(int)
    row_height=42

    def __init__(self,maximum,value=0,parent=None):
        super().__init__(parent)
        self.maximum=maximum;self.value=value;self.offset=0;self._press=None
        self.setFixedSize(100,self.row_height*5)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip('滚轮、上下拖动或方向键选择；点击上方或下方数字也可选择')

    def step(self,delta):
        self.value=(self.value+delta)%(self.maximum+1)
        self.valueChanged.emit(self.value);self.update()

    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        center=self.height()/2
        painter.fillRect(0,int(center-self.row_height/2),self.width(),self.row_height,QColor('#253d52'))
        for i in range(-3,4):
            y=center+i*self.row_height+self.offset
            painter.setPen(QColor('#f3f8fc' if i==0 else '#91a4b6'))
            font=QFont(self.font());font.setPointSize(22 if i==0 else 17);font.setBold(i==0)
            painter.setFont(font)
            painter.drawText(0,int(y-self.row_height/2),self.width(),self.row_height,
                             Qt.AlignmentFlag.AlignCenter,f'{(self.value+i)%(self.maximum+1):02d}')

    def wheelEvent(self,event):
        delta=event.angleDelta().y() or event.pixelDelta().y()
        if delta:self.step(-1 if delta>0 else 1)
        event.accept()

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Up,Qt.Key.Key_Down):
            self.step(-1 if event.key()==Qt.Key.Key_Up else 1);event.accept()
        else:super().keyPressEvent(event)

    def mousePressEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton:return
        self._press=event.position().y();self._last=self._press;self._moved=0
        self.setCursor(Qt.CursorShape.ClosedHandCursor);self.setFocus()

    def mouseMoveEvent(self,event):
        if self._press is None:return
        y=event.position().y();delta=y-self._last;self._last=y
        self._moved+=abs(delta);self.offset+=delta
        while self.offset>=self.row_height:self.offset-=self.row_height;self.step(-1)
        while self.offset<=-self.row_height:self.offset+=self.row_height;self.step(1)
        self.update()

    def mouseReleaseEvent(self,event):
        if self._press is None:return
        if self._moved<4:
            self.step(round((event.position().y()-self.height()/2)/self.row_height))
        elif abs(self.offset)>=self.row_height/2:
            self.step(-1 if self.offset>0 else 1)
        self._press=None;self.offset=0;self.setCursor(Qt.CursorShape.OpenHandCursor);self.update()


class TimeDialog(QDialog):
    def __init__(self,value,parent=None):
        super().__init__(parent)
        self.setWindowTitle('选择时间');self.setModal(True)
        layout=QVBoxLayout(self)
        hint=QLabel('上下拖动或滚动鼠标滚轮选择时间');layout.addWidget(hint)
        row=QHBoxLayout();layout.addLayout(row)
        self.hours=TimeWheel(23,value.hour(),self);self.hours.setAccessibleName('小时')
        self.minutes=TimeWheel(59,value.minute(),self);self.minutes.setAccessibleName('分钟')
        for title,wheel in [('小时',self.hours),('分钟',self.minutes)]:
            column=QVBoxLayout();label=QLabel(title);label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(label);column.addWidget(wheel);row.addLayout(column)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('确定')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def time(self):return QTime(self.hours.value,self.minutes.value)


class TimeInput(QWidget):
    def __init__(self,value,parent=None):
        super().__init__(parent)
        row=QHBoxLayout(self);row.setContentsMargins(0,0,0,0)
        self.edit=QLineEdit();self.edit.setPlaceholderText('HH:MM，如 08:30');self.edit.setMaxLength(5)
        self.edit.setMinimumWidth(145);self.edit.setMaximumWidth(180)
        self.edit.setAccessibleName('输入时间，24 小时制 HH:MM')
        self.edit.setToolTip('直接输入时间，例如 08:30 或 15:00')
        self.button=QPushButton('滚动选择…');self.button.clicked.connect(self.choose)
        self.edit.editingFinished.connect(self.normalize)
        row.addWidget(self.edit);row.addWidget(self.button);row.addStretch()
        self.setTime(value)

    def setTime(self,value):self.edit.setText(value.toString('HH:mm'))

    def time(self):
        match=re.fullmatch(r'([0-9]{1,2}):([0-9]{1,2})',self.edit.text().strip())
        return QTime(int(match[1]),int(match[2])) if match else QTime()

    def normalize(self):
        value=self.time()
        if value.isValid():self.setTime(value)

    def choose(self):
        value=self.time()
        dialog=TimeDialog(value if value.isValid() else QTime(8,0),self)
        try:
            if dialog.exec()==QDialog.DialogCode.Accepted:self.setTime(dialog.time())
        finally:dialog.deleteLater()

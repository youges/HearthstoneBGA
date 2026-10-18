"""Windows backend for the user's standalone application.

Not used by offline tests to operate third-party applications.
"""
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
from pathlib import Path
import subprocess
import threading
import time

import numpy as np


user32 = C.WinDLL('user32', use_last_error=True)
kernel32 = C.WinDLL('kernel32', use_last_error=True)
ULONG_PTR = C.c_size_t


class MOUSEINPUT(C.Structure):
    _fields_ = [('dx', W.LONG),('dy', W.LONG),('mouseData', W.DWORD),('dwFlags', W.DWORD),('time', W.DWORD),('dwExtraInfo', ULONG_PTR)]


class KEYBDINPUT(C.Structure):
    _fields_ = [('wVk', W.WORD),('wScan', W.WORD),('dwFlags', W.DWORD),('time', W.DWORD),('dwExtraInfo', ULONG_PTR)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [('uMsg', W.DWORD),('wParamL', W.WORD),('wParamH', W.WORD)]


class INPUTUNION(C.Union):
    _fields_ = [('mi',MOUSEINPUT),('ki',KEYBDINPUT),('hi',HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ('u',)
    _fields_ = [('type', W.DWORD),('u', INPUTUNION)]


user32.SendInput.argtypes = [W.UINT, C.POINTER(INPUT), C.c_int]
user32.SendInput.restype = W.UINT
user32.GetForegroundWindow.restype = W.HWND
user32.IsWindow.argtypes = [W.HWND]
user32.IsWindow.restype = W.BOOL
user32.IsWindowVisible.argtypes = [W.HWND]
user32.IsIconic.argtypes = [W.HWND]
user32.SetForegroundWindow.argtypes = [W.HWND]
user32.SetForegroundWindow.restype = W.BOOL
user32.ShowWindow.argtypes = [W.HWND,C.c_int]
user32.BringWindowToTop.argtypes = [W.HWND]
user32.BringWindowToTop.restype = W.BOOL
user32.AttachThreadInput.argtypes = [W.DWORD,W.DWORD,W.BOOL]
user32.AttachThreadInput.restype = W.BOOL
kernel32.GetCurrentThreadId.restype = W.DWORD
user32.GetClientRect.argtypes = [W.HWND,C.POINTER(W.RECT)]
user32.GetWindowRect.argtypes = [W.HWND,C.POINTER(W.RECT)]
user32.SetWindowPos.argtypes = [W.HWND,W.HWND,C.c_int,C.c_int,C.c_int,C.c_int,W.UINT]
user32.SetWindowPos.restype = W.BOOL
user32.ClientToScreen.argtypes = [W.HWND,C.POINTER(W.POINT)]
user32.GetWindowTextLengthW.argtypes = [W.HWND]
user32.GetWindowTextW.argtypes = [W.HWND,W.LPWSTR,C.c_int]
user32.GetWindowThreadProcessId.argtypes = [W.HWND,C.POINTER(W.DWORD)]
user32.GetAncestor.argtypes = [W.HWND,W.UINT]
user32.GetAncestor.restype = W.HWND
user32.WindowFromPoint.argtypes = [W.POINT]
user32.WindowFromPoint.restype = W.HWND
user32.SetCursorPos.argtypes = [C.c_int,C.c_int]
user32.GetCursorPos.argtypes = [C.POINTER(W.POINT)]
user32.GetAsyncKeyState.argtypes = [C.c_int]
user32.GetAsyncKeyState.restype = W.SHORT
kernel32.OpenProcess.argtypes = [W.DWORD,W.BOOL,W.DWORD]
kernel32.OpenProcess.restype = W.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)]
kernel32.CloseHandle.argtypes = [W.HANDLE]
ENUMPROC = C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
user32.EnumWindows.argtypes = [ENUMPROC,W.LPARAM]
user32.MonitorFromWindow.argtypes=[W.HWND,W.DWORD]
user32.MonitorFromWindow.restype=W.HANDLE
user32.GetMonitorInfoW.argtypes=[W.HANDLE,C.c_void_p]
user32.GetMonitorInfoW.restype=W.BOOL
user32.GetDpiForWindow.argtypes=[W.HWND]
user32.GetDpiForWindow.restype=W.UINT
user32.SetThreadDpiAwarenessContext.argtypes=[C.c_void_p]
user32.SetThreadDpiAwarenessContext.restype=C.c_void_p


class MONITORINFO(C.Structure):
    _fields_=[('cbSize',W.DWORD),('rcMonitor',W.RECT),('rcWork',W.RECT),('dwFlags',W.DWORD)]


class InputCancelled(RuntimeError):
    pass


class WindowUnavailable(RuntimeError):
    pass


def input_idle_seconds():
    class LASTINPUTINFO(C.Structure):
        _fields_=[('cbSize',W.UINT),('dwTime',W.DWORD)]
    info=LASTINPUTINFO();info.cbSize=C.sizeof(info)
    if not user32.GetLastInputInfo(C.byref(info)):
        return 0.0
    return ((kernel32.GetTickCount()-info.dwTime)&0xffffffff)/1000


@dataclass
class Window:
    hwnd: int
    title: str
    exe: str
    kind: str

    def activate(self):
        user32.ShowWindow(self.hwnd,9)
        if user32.GetForegroundWindow()==self.hwnd:
            return
        user32.SetForegroundWindow(self.hwnd)
        if user32.GetForegroundWindow()!=self.hwnd:
            foreground=user32.GetForegroundWindow()
            foreground_thread=user32.GetWindowThreadProcessId(foreground,None) if foreground else 0
            own_thread=kernel32.GetCurrentThreadId()
            target_thread=user32.GetWindowThreadProcessId(self.hwnd,None)
            attached=[]
            try:
                for thread in set([foreground_thread,target_thread]):
                    if thread and thread!=own_thread and user32.AttachThreadInput(own_thread,thread,True):
                        attached.append(thread)
                user32.ShowWindow(self.hwnd,9)
                user32.BringWindowToTop(self.hwnd)
                user32.SetForegroundWindow(self.hwnd)
            finally:
                for thread in reversed(attached):
                    user32.AttachThreadInput(own_thread,thread,False)
        if user32.GetForegroundWindow()!=self.hwnd:
            raise WindowUnavailable('无法激活目标窗口，请切回战网/游戏后继续')

    def rect(self):
        rect, origin = W.RECT(), W.POINT(0,0)
        if not user32.IsWindow(self.hwnd) or user32.IsIconic(self.hwnd):
            raise WindowUnavailable('目标窗口已关闭或最小化')
        if not user32.GetClientRect(self.hwnd,C.byref(rect)) or not user32.ClientToScreen(self.hwnd,C.byref(origin)):
            raise WindowUnavailable('无法读取目标客户区')
        width,height = rect.right-rect.left,rect.bottom-rect.top
        if width < 320 or height < 240:
            raise WindowUnavailable('目标客户区太小')
        return origin.x,origin.y,width,height

    def check(self, rect=None):
        current = self.rect()
        if rect is not None and current != rect:
            raise WindowUnavailable('窗口位置或大小改变，旧动作已取消')
        if user32.GetForegroundWindow() != self.hwnd:
            raise WindowUnavailable('目标不在前台；请切回战网/炉石窗口后继续')
        return current

    def check_point(self,x,y):
        at=user32.WindowFromPoint(W.POINT(x,y))
        root=user32.GetAncestor(at,2) if at else None
        if root!=self.hwnd:
            raise WindowUnavailable('操作位置被其他窗口遮挡；已停止输入')

    def adapt_resolution(self,aspect):
        from .adaptation import fit_client,needs_fit
        info=MONITORINFO();info.cbSize=C.sizeof(info)
        monitor=user32.MonitorFromWindow(self.hwnd,2)
        if not user32.GetMonitorInfoW(monitor,C.byref(info)):
            raise WindowUnavailable('无法获取目标显示器工作区')
        wr=info.rcWork;work=(wr.left,wr.top,wr.right,wr.bottom)
        outer=W.RECT()
        if not user32.GetWindowRect(self.hwnd,C.byref(outer)):
            raise WindowUnavailable('无法读取目标窗口边框')
        current=self.rect();outer_rect=(outer.left,outer.top,outer.right,outer.bottom)
        changed=False
        if needs_fit(current,outer_rect,work,aspect):
            # Fullscreen modes are not forcibly toggled. A denied resize will fail validation.
            user32.ShowWindow(self.hwnd,9)
            time.sleep(.15)
            current=self.rect();user32.GetWindowRect(self.hwnd,C.byref(outer))
            border=(outer.right-outer.left-current[2],outer.bottom-outer.top-current[3])
            try:plan=fit_client(work,border,aspect)
            except ValueError as e:raise WindowUnavailable(str(e)) from e
            if not user32.SetWindowPos(self.hwnd,None,*plan,0x0014):
                raise WindowUnavailable('自动适配窗口失败，请将游戏切换为窗口模式')
            time.sleep(.45)
            current=self.rect();user32.GetWindowRect(self.hwnd,C.byref(outer))
            actual_outer=(outer.left,outer.top,outer.right,outer.bottom)
            if needs_fit(current,actual_outer,work,aspect):
                raise WindowUnavailable('窗口未接受适配尺寸，请切换窗口模式，或关闭自动适配后重新校准')
            changed=True
        return dict(client_rect=current,work_area=work,dpi=int(user32.GetDpiForWindow(self.hwnd) or 96),
                    aspect=aspect,changed=changed)


def find_windows():
    result = []
    @ENUMPROC
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        buf = C.create_unicode_buffer(length+1)
        user32.GetWindowTextW(hwnd,buf,len(buf))
        pid = W.DWORD()
        user32.GetWindowThreadProcessId(hwnd,C.byref(pid))
        proc = kernel32.OpenProcess(0x1000,False,pid.value)
        if not proc:
            return True
        try:
            path = C.create_unicode_buffer(32768)
            size = W.DWORD(len(path))
            if not kernel32.QueryFullProcessImageNameW(proc,0,path,C.byref(size)):
                return True
            name = Path(path.value).name.lower()
            if name == 'hearthstone.exe':
                result.append(Window(int(hwnd),buf.value,path.value,'game'))
            elif name == 'battle.net.exe' or (buf.value == '战网' and 'battle.net' in path.value.lower()):
                result.append(Window(int(hwnd),buf.value,path.value,'launcher'))
        finally:
            kernel32.CloseHandle(proc)
        return True
    user32.EnumWindows(callback,0)
    return result


def pick_window():
    windows = find_windows()
    game = [w for w in windows if w.kind == 'game']
    candidates = game or [w for w in windows if w.kind == 'launcher']
    if len(candidates) > 1:
        focused = [w for w in candidates if w.hwnd == user32.GetForegroundWindow()]
        if len(focused) != 1:
            raise WindowUnavailable('检测到多个目标窗口，需要保留一个或将目标置于前台')
        return focused[0]
    return candidates[0] if candidates else None


def launch_battle_net(executable):
    path = Path(executable).resolve()
    if not path.is_file() or path.suffix.lower() != '.exe':
        raise ValueError('战网可执行文件不存在，请在设置中选择')
    subprocess.Popen([str(path)],cwd=str(path.parent),shell=False)


class WindowsBackend:
    def __init__(self, stop: threading.Event, pause: threading.Event):
        import mss
        self.previous_dpi=user32.SetThreadDpiAwarenessContext(C.c_void_p(-4))
        self.capture = mss.mss()
        self.stop,self.pause = stop,pause

    def screenshot(self, window):
        rect = window.check()
        x,y,w,h = rect
        frame = np.asarray(self.capture.grab(dict(left=x,top=y,width=w,height=h)))[:,:,:3].copy()
        window.check(rect)
        return frame,rect

    def cancelled(self):
        if user32.GetAsyncKeyState(0x78)&0x8000:  # F9
            self.stop.set()
        if user32.GetAsyncKeyState(0x77)&0x8000:  # F8, including during a drag
            self.pause.set()
        if self.stop.is_set() or self.pause.is_set():
            raise InputCancelled('输入已取消')

    def send(self, item):
        count = user32.SendInput(1,C.byref(item),C.sizeof(INPUT))
        if count != 1:
            raise WindowUnavailable('SendInput 未插入事件，可能受权限等级/UIPI 限制')

    def mouse(self, flag):
        item = INPUT(type=0)
        item.mi.dwFlags = flag
        self.send(item)

    def wait(self, seconds):
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            self.cancelled()
            self.stop.wait(min(.025,max(0,end-time.monotonic())))

    def execute(self, window, action, obs, rect):
        self.cancelled()
        if time.monotonic()-action.captured_at > 6:
            raise WindowUnavailable('识别画面已超过 6 秒，取消旧动作')
        window.check(rect)
        x,y,w,h = rect
        def position(name):
            fx,fy = obs.targets[name]
            if not 0 < fx < 1 or not 0 < fy < 1:
                raise WindowUnavailable('目标坐标超出客户区')
            return round(x+w*fx),round(y+h*fy)
        if action.kind == 'key':
            if action.key != 'Escape':
                raise ValueError('当前只允许 Escape 按键')
            key = INPUT(type=1)
            key.ki.wVk = 0x1B
            self.send(key)
            try:
                self.wait(.08)
            finally:
                key.ki.dwFlags = 2
                self.send(key)
            return
        start = position(action.target)
        window.check_point(*start)
        if action.kind=='drag':
            window.check_point(*position(action.destination))
        if not user32.SetCursorPos(*start):
            raise WindowUnavailable('鼠标定位失败')
        self.wait(.1)
        window.check(rect)
        window.check_point(*start)
        if action.kind=='hover':
            self.wait(.3)
            return
        pressed = False
        try:
            self.cancelled()
            self.mouse(0x2)
            pressed = True
            if action.kind == 'drag':
                self.wait(.15)
                end = position(action.destination)
                for i in range(1,25):
                    self.cancelled()
                    if user32.GetForegroundWindow() != window.hwnd or window.rect() != rect:
                        raise WindowUnavailable('拖拽期间目标改变，已释放鼠标')
                    t=i/24
                    point=(round(start[0]+(end[0]-start[0])*t),round(start[1]+(end[1]-start[1])*t))
                    window.check_point(*point)
                    user32.SetCursorPos(*point)
                    self.wait(.025)
                self.wait(.12)
            else:
                self.wait(.08)
        finally:
            if pressed:
                self.mouse(0x4)
        self.wait(.15)
        if user32.GetForegroundWindow()==window.hwnd:
            park=(round(x+w*.97),round(y+h*.35))
            try:window.check_point(*park)
            except WindowUnavailable:return
            user32.SetCursorPos(*park)

    def close(self):
        self.capture.close()
        if getattr(self,'previous_dpi',None):
            user32.SetThreadDpiAwarenessContext(self.previous_dpi)

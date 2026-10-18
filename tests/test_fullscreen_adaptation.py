"""Regression: a fullscreen game must not be resized to exclude the taskbar."""
import sys
from types import SimpleNamespace

import pytest

from bga.adaptation import covers_monitor,needs_fit


@pytest.mark.parametrize('monitor,work',[
    ((0,0,1920,1080),(0,0,1920,1020)),
    ((0,0,1920,1080),(60,0,1920,1080)),
    ((0,0,1920,1080),(0,60,1920,1080)),
    ((-2560,0,0,1440),(-2560,0,0,1380)),
    ((0,0,3840,2160),(0,0,3840,2080)),
])
def test_fullscreen_uses_whole_monitor_not_desktop_work_area(monkeypatch,monitor,work):
    if sys.platform!='win32':pytest.skip('Win32 adapter')
    import bga.windows as native

    left,top,right,bottom=monitor
    client=(left,top,right-left,bottom-top)
    assert needs_fit(client,monitor,work,16/9),'旧逻辑会将此全屏误判为越界'

    def get_info(handle,pointer):
        pointer._obj.rcMonitor=native.W.RECT(*monitor)
        pointer._obj.rcWork=native.W.RECT(*work)
        return True

    def get_rect(handle,pointer):
        pointer._obj.left,pointer._obj.top,pointer._obj.right,pointer._obj.bottom=monitor
        return True

    def forbidden(*args):
        pytest.fail('全屏适配不得调用恢复或调整窗口 API')

    api=SimpleNamespace(MonitorFromWindow=lambda *args:1,GetMonitorInfoW=get_info,
                        GetWindowRect=get_rect,GetWindowLongW=lambda *args:0x80000000,
                        GetDpiForWindow=lambda *args:120,ShowWindow=forbidden,SetWindowPos=forbidden)
    monkeypatch.setattr(native,'user32',api)
    monkeypatch.setattr(native.Window,'rect',lambda self:client)
    target=native.Window(1,'fullscreen fixture','','game')
    result=target.adapt_resolution(16/9)
    assert result['mode']=='fullscreen' and not result['changed']
    assert result['client_rect']==client and result['monitor_area']==monitor
    assert result==target.adapt_resolution(16/9)
    with pytest.raises(native.WindowUnavailable,match='全屏画面比例'):
        target.adapt_resolution(4/3)


def test_fullscreen_detection_does_not_accept_small_or_displaced_windows():
    monitor=(0,0,1920,1080)
    assert covers_monitor((0,0,1920,1080),monitor)
    assert covers_monitor((-1,-1,1922,1082),monitor)
    assert not covers_monitor((0,0,1920,1020),monitor)
    assert not covers_monitor((100,100,1920,1080),monitor)
    assert not covers_monitor((0,0,1280,720),monitor)

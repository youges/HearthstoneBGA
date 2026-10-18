import ctypes
import threading
from unittest.mock import patch

import pytest

from bga.config import Config,Profile
from bga.model import Action,Match,Observation,State
from bga.store import Store
from bga.windows import INPUT,WindowsBackend,InputCancelled,Window,WindowUnavailable


def test_result_upsert_and_unknown_values(tmp_path):
    store=Store(tmp_path/'matches.sqlite3')
    try:
        match=Match('same-id','2026-10-15T16:00:00+00:00')
        store.save(match);store.save(match)
        assert len(store.recent())==1
        assert store.recent()[0]['rating_delta'] is None
        match.rating_before=6000;match.rating_after=5950;store.save(match)
        assert store.recent()[0]['rating_delta']==-50
    finally:store.close()


def test_default_profile_is_explicitly_uncalibrated():
    profile=Profile()
    assert not profile.calibrated
    assert profile.missing()


def test_default_configuration_is_observe_only():
    assert Config().observe_only


def test_win64_input_structure_matches_windows_abi():
    assert ctypes.sizeof(INPUT)==(40 if ctypes.sizeof(ctypes.c_void_p)==8 else 28)


def test_stop_cancels_before_any_input():
    backend=WindowsBackend.__new__(WindowsBackend)
    backend.stop=threading.Event();backend.pause=threading.Event();backend.stop.set()
    with patch('bga.windows.user32.GetAsyncKeyState',return_value=0):
        with pytest.raises(InputCancelled):backend.cancelled()


def test_drag_always_releases_mouse_when_cancelled():
    backend=WindowsBackend.__new__(WindowsBackend)
    backend.stop=threading.Event();backend.pause=threading.Event()
    calls=[]
    backend.mouse=lambda flag:calls.append(flag)
    backend.wait=lambda seconds:None
    count=[0]
    def cancel():
        count[0]+=1
        if count[0]>=3:raise InputCancelled('test')
    backend.cancelled=cancel
    class FakeWindow:
        hwnd=123
        def rect(self):return (0,0,800,450)
        def check(self,rect=None):return self.rect()
        def check_point(self,x,y):pass
    import time
    obs=Observation(State.RECRUIT,targets={'shop_1':(.3,.3),'hand_drop':(.5,.9)})
    action=Action('drag','buy','shop_1','hand_drop',source_state=State.RECRUIT,captured_at=time.monotonic())
    with patch('bga.windows.user32.SetCursorPos',return_value=True),patch('bga.windows.user32.GetForegroundWindow',return_value=123):
        with pytest.raises(InputCancelled):backend.execute(FakeWindow(),action,obs,(0,0,800,450))
    assert calls==[2,4]


def test_occluded_point_is_rejected():
    target=Window(123,'game','Hearthstone.exe','game')
    with patch('bga.windows.user32.WindowFromPoint',return_value=456),patch('bga.windows.user32.GetAncestor',return_value=456):
        with pytest.raises(WindowUnavailable,match='遮挡'):
            target.check_point(300,200)



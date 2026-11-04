from datetime import datetime
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTime

from bga.config import Config
from bga.schedule import window, sync_task
from bga.gui import MainWindow
from bga.model import Observation, State
from conftest import settle


@pytest.mark.parametrize('start,end,now,expected',[
    ('08:00','15:00','2026-11-04 07:59','2026-11-04 08:00|2026-11-04 15:00'),
    ('08:00','15:00','2026-11-04 08:00','2026-11-04 08:00|2026-11-04 15:00'),
    ('08:00','15:00','2026-11-04 15:00','2026-11-05 08:00|2026-11-05 15:00'),
    ('22:00','03:00','2026-11-04 01:00','2026-11-03 22:00|2026-11-04 03:00'),
    ('22:00','03:00','2026-11-04 03:00','2026-11-04 22:00|2026-11-05 03:00'),
])
def test_daily_and_overnight_boundaries(start,end,now,expected):
    a,b=window(Config(schedule_start=start,schedule_end=end),datetime.fromisoformat(now))
    assert a.strftime('%Y-%m-%d %H:%M')+'|'+b.strftime('%Y-%m-%d %H:%M')==expected


def test_schedule_has_priority_over_completed_match_limit(world,targets):
    engine,_,clock=world
    engine.config.max_matches=3;engine.config.close_after_matches=True
    engine.config.schedule_enabled=True;engine.completed=3
    obs=Observation(State.LOBBY,.99,True,targets,metrics={'rating':2000})
    settle(engine,clock,obs)
    assert not engine.done
    engine.config.schedule_enabled=False
    engine.observe(obs)
    assert engine.done


def test_schedule_task_is_interactive_and_has_no_password(tmp_path,monkeypatch):
    from bga import schedule
    calls=[]
    monkeypatch.setattr(schedule.subprocess,'run',lambda args,**kw:(calls.append(args) or SimpleNamespace(returncode=0,stdout=b'',stderr=b'')))
    monkeypatch.setattr(schedule.subprocess,'check_output',lambda *a,**kw:'DOMAIN\\tester\n')
    sync_task(Config(schedule_enabled=True),tmp_path)
    root=ET.parse(tmp_path/'data/daily-schedule.xml').getroot();ns={'t':root.tag.split('}')[0][1:]}
    assert root.find('.//t:LogonType',ns).text=='InteractiveToken'
    assert '--scheduled-run' in root.find('.//t:Arguments',ns).text
    assert root.find('.//t:WorkingDirectory',ns).text==str(tmp_path.resolve())
    assert calls[-1][1]=='/Create'
    sync_task(Config(),tmp_path)
    assert calls[-1][1]=='/Delete'


def test_gui_persists_independent_switches_and_handles_registration_failure(tmp_path,monkeypatch):
    from bga import schedule
    app=QApplication.instance() or QApplication([]);w=MainWindow(tmp_path)
    calls=[];warnings=[]
    monkeypatch.setattr(schedule,'sync_task',lambda c,r:calls.append(c.schedule_enabled))
    monkeypatch.setattr(QMessageBox,'warning',lambda *a:warnings.append(a[-1]))
    try:
        w.controls['close_after_matches'].setChecked(True)
        w.controls['max_matches'].setValue(3)
        w.controls['schedule_enabled'].setChecked(True)
        w.controls['schedule_start'].setTime(QTime(8,0));w.controls['schedule_end'].setTime(QTime(15,0))
        w.save_settings();c=Config.load(w.config_path)
        assert c.close_after_matches and c.schedule_enabled and c.max_matches==3
        assert c.schedule_start=='08:00' and c.schedule_end=='15:00' and calls==[True]
        def denied(*args):raise OSError('task permission denied')
        monkeypatch.setattr(schedule,'sync_task',denied)
        w.controls['schedule_enabled'].setChecked(False);w.save_settings()
        assert Config.load(w.config_path).schedule_enabled and w.config.schedule_enabled and warnings
    finally:w.close();app.processEvents()


@pytest.mark.parametrize('reason,scheduled,close_count,closed',[
    ('schedule_end',True,False,True),('match_limit',False,True,True),
    ('match_limit',True,True,False),('',False,True,False),('match_limit',False,False,False),
])
def test_only_requested_completion_closes_window(tmp_path,reason,scheduled,close_count,closed,monkeypatch):
    app=QApplication.instance() or QApplication([]);w=MainWindow(tmp_path);calls=[]
    w.config.schedule_enabled=scheduled;w.config.close_after_matches=close_count
    w.worker=SimpleNamespace(end_reason=reason)
    monkeypatch.setattr(w,'close',lambda:calls.append(True))
    w.run_finished();assert bool(calls)==closed
    w.worker=None;w.schedule_timer.stop();w.deleteLater();app.processEvents()


@pytest.mark.parametrize('values',[
    {'schedule_start':'24:00'}, {'schedule_end':'8:00'},
    {'schedule_enabled':True,'schedule_start':'08:00','schedule_end':'08:00'},
    {'close_after_matches':True,'max_matches':0},
])
def test_invalid_schedule_settings_are_rejected(values):
    with pytest.raises(ValueError):Config(**values).validate()


def test_wait_can_be_cancelled_after_previous_worker_finished(tmp_path,monkeypatch):
    from bga import schedule
    app=QApplication.instance() or QApplication([]);w=MainWindow(tmp_path)
    try:
        w.config.schedule_enabled=True;w.schedule_armed=True
        w.worker=SimpleNamespace(isRunning=lambda:False)
        monkeypatch.setattr(schedule,'window',lambda c:(datetime(2099,1,1,8),datetime(2099,1,1,15)))
        w.schedule_tick()
        assert w.stop_button.isEnabled() and not w.start_button.isEnabled()
        w.stop_run()
        assert not w.schedule_armed and w.start_button.isEnabled()
        calls=[];monkeypatch.setattr(w,'start_run',lambda:calls.append(True))
        monkeypatch.setattr(schedule,'window',lambda c:(datetime(2000,1,1,8),datetime(2099,1,1,15)))
        w.schedule_tick();assert not calls
        w.schedule_armed=True;w.schedule_tick();w.schedule_tick()
        assert calls==[True]
    finally:w.worker=None;w.close();app.processEvents()


def test_schedule_deadline_stops_a_paused_worker(tmp_path):
    app=QApplication.instance() or QApplication([]);w=MainWindow(tmp_path);calls=[]
    try:
        w.worker=SimpleNamespace(isRunning=lambda:True,schedule_deadline=datetime(2000,1,1),
                                 end_reason='',stop=lambda:calls.append(True),paused=True)
        w.schedule_tick()
        assert calls==[True] and w.worker.end_reason=='schedule_end'
    finally:w.worker=None;w.close();app.processEvents()

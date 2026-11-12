from datetime import datetime
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTime,QDate

from bga.config import Config
from bga.schedule import window, sync_task, ScheduleExpired
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


@pytest.mark.parametrize('days,start,end,now,expected',[
    ([0,2,4],'08:00','15:00','2026-11-10 10:00','2026-11-11 08:00|2026-11-11 15:00'),
    ([0],'08:00','15:00','2026-11-09 08:00','2026-11-09 08:00|2026-11-09 15:00'),
    ([0],'08:00','15:00','2026-11-09 15:00','2026-11-16 08:00|2026-11-16 15:00'),
    ([5,6],'08:00','15:00','2026-11-09 10:00','2026-11-14 08:00|2026-11-14 15:00'),
    ([0],'22:00','03:00','2026-11-10 01:00','2026-11-09 22:00|2026-11-10 03:00'),
    ([0],'22:00','03:00','2026-11-10 03:00','2026-11-16 22:00|2026-11-17 03:00'),
    ([1],'22:00','03:00','2026-11-10 01:00','2026-11-10 22:00|2026-11-11 03:00'),
    ([6],'22:00','03:00','2026-11-09 01:00','2026-11-08 22:00|2026-11-09 03:00'),
    ([0],'08:00','15:00','2026-12-28 15:00','2027-01-04 08:00|2027-01-04 15:00'),
])
def test_weekly_windows_skip_unselected_days_and_keep_start_day(days,start,end,now,expected):
    config=Config(schedule_weekdays=days,schedule_start=start,schedule_end=end)
    a,b=window(config,datetime.fromisoformat(now))
    assert a.strftime('%Y-%m-%d %H:%M')+'|'+b.strftime('%Y-%m-%d %H:%M')==expected


def test_legacy_config_keeps_daily_schedule_and_default_lists_are_independent(tmp_path):
    path=tmp_path/'config.json'
    path.write_text('{"schedule_enabled":true}',encoding='utf-8')
    assert Config.load(path).schedule_weekdays==list(range(7))
    a,b=Config(),Config()
    a.schedule_weekdays.clear()
    assert b.schedule_weekdays==list(range(7))
    assert Config.load(path).schedule_mode=='weekdays' and not Config.load(path).schedule_dates


@pytest.mark.parametrize('now,start,end,expected',[
    ('2026-11-12 09:00','08:00','15:00','2026-11-12 08:00|2026-11-12 15:00'),
    ('2026-11-13 09:00','08:00','15:00','2026-11-20 08:00|2026-11-20 15:00'),
    ('2026-11-13 01:00','22:00','03:00','2026-11-12 22:00|2026-11-13 03:00'),
    ('2026-11-13 03:00','22:00','03:00','2026-11-20 22:00|2026-11-21 03:00'),
])
def test_specific_dates_run_once_and_respect_overnight_finish(now,start,end,expected):
    config=Config(schedule_enabled=True,schedule_mode='dates',schedule_weekdays=[],
                  schedule_dates=['2026-11-20','2026-11-12'],schedule_start=start,schedule_end=end)
    a,b=window(config,datetime.fromisoformat(now))
    assert a.strftime('%Y-%m-%d %H:%M')+'|'+b.strftime('%Y-%m-%d %H:%M')==expected
    with pytest.raises(ScheduleExpired):window(config,datetime(2026,11,22))


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


@pytest.mark.parametrize('days,expected',[
    ([0,2,6],['Monday','Wednesday','Sunday']),
    (list(range(7)),['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']),
])
def test_schedule_task_is_interactive_and_has_no_password(tmp_path,monkeypatch,days,expected):
    from bga import schedule
    calls=[]
    monkeypatch.setattr(schedule.subprocess,'run',lambda args,**kw:(calls.append(args) or SimpleNamespace(returncode=0,stdout=b'',stderr=b'')))
    monkeypatch.setattr(schedule.subprocess,'check_output',lambda *a,**kw:'DOMAIN\\tester\n')
    sync_task(Config(schedule_enabled=True,schedule_weekdays=days),tmp_path)
    root=ET.parse(tmp_path/'data/daily-schedule.xml').getroot();ns={'t':root.tag.split('}')[0][1:]}
    assert root.find('.//t:LogonType',ns).text=='InteractiveToken'
    assert '--scheduled-run' in root.find('.//t:Arguments',ns).text
    assert root.find('.//t:WorkingDirectory',ns).text==str(tmp_path.resolve())
    weekly=root.find('.//t:ScheduleByWeek',ns)
    assert weekly.find('t:WeeksInterval',ns).text=='1'
    assert [x.tag.split('}')[1] for x in weekly.find('t:DaysOfWeek',ns)]==expected
    assert root.find('.//t:ScheduleByDay',ns) is None
    assert calls[-1][1]=='/Create'
    sync_task(Config(),tmp_path)
    assert calls[-1][1]=='/Delete'


def test_specific_dates_create_one_time_triggers_and_expired_schedule_removes_task(tmp_path,monkeypatch):
    from bga import schedule
    calls=[]
    monkeypatch.setattr(schedule.subprocess,'run',lambda args,**kw:(calls.append(args) or SimpleNamespace(returncode=0,stdout=b'',stderr=b'')))
    monkeypatch.setattr(schedule.subprocess,'check_output',lambda *a,**kw:'DOMAIN\\tester\n')
    config=Config(schedule_enabled=True,schedule_mode='dates',schedule_dates=['2099-01-05','2099-01-10'])
    sync_task(config,tmp_path)
    root=ET.parse(tmp_path/'data/daily-schedule.xml').getroot();ns={'t':root.tag.split('}')[0][1:]}
    assert root.find('.//t:CalendarTrigger',ns) is None
    assert [x.find('t:StartBoundary',ns).text for x in root.findall('.//t:TimeTrigger',ns)]==[
        '2099-01-05T08:00:00','2099-01-10T08:00:00']
    config.schedule_dates=['2000-01-01']
    sync_task(config,tmp_path)
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


def test_gui_weekday_only_change_updates_task_and_survives_reload(tmp_path,monkeypatch):
    from bga import schedule
    monkeypatch.setattr(schedule,'window',lambda c:(datetime(2099,1,1,8),datetime(2099,1,1,15)))
    app=QApplication.instance() or QApplication([]);w=MainWindow(tmp_path)
    calls=[];warnings=[]
    monkeypatch.setattr(schedule,'sync_task',lambda c,r:calls.append(list(c.schedule_weekdays)))
    monkeypatch.setattr(QMessageBox,'warning',lambda *a:warnings.append(a[-1]))
    try:
        w.controls['schedule_enabled'].setChecked(True)
        w.save_settings()
        for i,check in enumerate(w.weekday_checks):check.setChecked(i in (0,2,6))
        w.save_settings()
        assert calls==[list(range(7)),[0,2,6]]
        assert Config.load(w.config_path).schedule_weekdays==[0,2,6]
        restored=MainWindow(tmp_path)
        try:assert [i for i,c in enumerate(restored.weekday_checks) if c.isChecked()]==[0,2,6]
        finally:restored.close();app.processEvents()
        for check in w.weekday_checks:check.setChecked(False)
        w.save_settings()
        assert warnings and len(calls)==2
        assert Config.load(w.config_path).schedule_weekdays==[0,2,6]
        def denied(*args):raise OSError('task permission denied')
        monkeypatch.setattr(schedule,'sync_task',denied)
        w.weekday_checks[4].setChecked(True);w.save_settings()
        assert len(warnings)==2 and w.config.schedule_weekdays==[0,2,6]
        assert Config.load(w.config_path).schedule_weekdays==[0,2,6]
    finally:w.close();app.processEvents()


def test_gui_dates_calendar_list_and_direct_time_input_are_persisted(tmp_path,monkeypatch):
    from bga import schedule
    monkeypatch.setattr(schedule,'sync_task',lambda *a:None)
    app=QApplication.instance() or QApplication([]);w=MainWindow(tmp_path)
    try:
        w.schedule_timer.stop()
        w.schedule_mode.setCurrentIndex(1)
        for value in ('2099-01-10','2099-01-05','2099-01-10'):
            w.add_schedule_date(QDate.fromString(value,'yyyy-MM-dd'))
        assert w.date_list.count()==2
        w.date_list.item(1).setSelected(True);w.remove_schedule_dates()
        assert w.date_list.count()==1
        w.controls['schedule_start'].edit.setText('8:30')
        w.controls['schedule_end'].edit.setText('15:45')
        w.controls['schedule_enabled'].setChecked(True)
        w.save_settings()
        config=Config.load(w.config_path)
        assert config.schedule_mode=='dates' and config.schedule_dates==['2099-01-05']
        assert (config.schedule_start,config.schedule_end)==('08:30','15:45')
        restored=MainWindow(tmp_path);restored.schedule_timer.stop()
        try:
            assert restored.schedule_mode.currentData()=='dates'
            assert restored.date_list.item(0).text()=='2099-01-05'
            assert restored.controls['schedule_start'].edit.text()=='08:30'
        finally:restored.close();app.processEvents()
    finally:w.close();app.processEvents()


def test_gui_expired_dates_disarm_wait_without_starting_worker(tmp_path):
    app=QApplication.instance() or QApplication([]);w=MainWindow(tmp_path)
    try:
        w.config.schedule_enabled=True;w.config.schedule_mode='dates';w.config.schedule_dates=['2000-01-01']
        w.schedule_armed=True;w.schedule_tick()
        assert not w.schedule_armed and w.worker is None and w.start_button.isEnabled()
        assert '所选日期已全部结束' in w.state_label.text()
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
    {'schedule_enabled':True,'schedule_weekdays':[]},
    {'schedule_weekdays':[7]}, {'schedule_weekdays':[-1]},
    {'schedule_weekdays':[True]}, {'schedule_weekdays':['1']},
    {'schedule_weekdays':[1,1]}, {'schedule_weekdays':None},
    {'schedule_mode':'invalid'}, {'schedule_dates':None},
    {'schedule_enabled':True,'schedule_mode':'dates','schedule_dates':[]},
    {'schedule_dates':['2026-02-30']}, {'schedule_dates':['20261112']},
    {'schedule_dates':[True]}, {'schedule_dates':['2026-11-12','2026-11-12']},
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

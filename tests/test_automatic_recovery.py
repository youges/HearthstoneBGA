"""Bounded error concessions must record their cause and wait for the lobby."""
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from bga.config import Config,Profile
from bga.engine import Engine,NeedsAttention
from bga.model import Observation,State
from bga.store import Store
from conftest import settle


def points(targets):return dict(targets,concede=(.5,.45),confirm_concede=(.6,.55))


def active(world,targets):
    engine,store,clock=world
    engine.config.auto_concede_on_error=True
    obs=Observation(State.RECRUIT,.99,True,points(targets),
                    metrics={'gold':10,'upgrade_cost':4,'tavern_tier':3},board_count=3)
    settle(engine,clock,obs)
    return engine,store,clock,obs


def fail_feedback(engine,clock,obs):
    for _ in range(3):
        action=engine.decide(obs)
        assert action.target=='upgrade'
        engine.sent(action,obs)
        clock.advance(9)
    with pytest.raises(NeedsAttention) as caught:engine.decide(obs)
    assert caught.value.recoverable
    return caught.value


def finish_recovery(engine,clock,obs,placement=8,rating=5900):
    escape=engine.decide(obs)
    assert escape.kind=='key' and escape.key=='Escape'
    engine.sent(escape,obs)
    menu=Observation(State.MENU,.99,True,obs.targets)
    settle(engine,clock,menu)
    concede=engine.decide(menu)
    assert concede.target=='concede'
    engine.sent(concede,menu)
    confirm=Observation(State.CONFIRM,.99,True,obs.targets)
    settle(engine,clock,confirm)
    click=engine.decide(confirm)
    assert click.target=='confirm_concede'
    engine.sent(click,confirm)
    # Animation frames may not cause another tavern action.
    settle(engine,clock,obs)
    assert engine.decide(obs) is None
    result=Observation(State.RESULT,.99,True,obs.targets,metrics={'placement':placement,'rating':rating})
    settle(engine,clock,result,4)
    leave=engine.decide(result)
    assert leave.target=='result_continue'
    engine.sent(leave,result)
    lobby=Observation(State.LOBBY,.99,True,obs.targets,metrics={'rating':rating})
    settle(engine,clock,lobby,4)
    return lobby


def test_real_feedback_failure_runs_concession_records_reason_and_requeues(world,targets):
    engine,store,clock,obs=active(world,targets)
    reason=fail_feedback(engine,clock,obs)
    match_id=engine.match.id
    assert engine.begin_recovery(obs,reason)
    assert store.recent()[0]['end_reason']=='normal'
    assert store.recent()[0]['recovery_reason']==str(reason)
    lobby=finish_recovery(engine,clock,obs)
    record=store.recent()[0]
    assert record['id']==match_id and record['end_reason']=='auto_recovery'
    assert record['placement']==8 and record['rating_after']==5900
    assert record['result_status']=='complete' and engine.completed==1
    assert engine.recovery is None and engine.recovery_streak==1
    assert engine.decide(lobby).target=='lobby_play'


@pytest.mark.parametrize('changed',['disabled','observe_only','no_match','ended','before_play',
                                    'authentication','disconnect','missing_point','wrong_window',
                                    'not_recoverable','already_recovering'])
def test_recovery_cannot_start_outside_authorized_conditions(world,targets,changed):
    engine,_,clock,obs=active(world,targets)
    reason=NeedsAttention('failed',recoverable=True)
    kind='game'
    if changed=='disabled':engine.config.auto_concede_on_error=False
    if changed=='observe_only':engine.config.observe_only=True
    if changed=='no_match':engine.match=None
    if changed=='ended':engine.match.ended_at='2026-10-25T00:00:00+00:00'
    if changed=='before_play':engine.match_play_seen=False
    if changed=='authentication':obs.state=State.AUTH
    if changed=='disconnect':obs.state=State.DISCONNECT
    if changed=='missing_point':obs.targets.pop('confirm_concede')
    if changed=='wrong_window':kind='launcher'
    if changed=='not_recoverable':reason=NeedsAttention('missing calibration')
    if changed=='already_recovering':
        assert engine.begin_recovery(obs,reason)
    assert not engine.begin_recovery(obs,reason,kind)


def test_unknown_timeout_can_probe_escape_but_never_blindly_click(world,targets):
    engine,_,clock,obs=active(world,targets)
    unknown=Observation(State.UNKNOWN,targets=obs.targets)
    settle(engine,clock,unknown)
    clock.advance(engine.config.state_timeout+1)
    with pytest.raises(NeedsAttention) as caught:engine.decide(unknown)
    assert engine.begin_recovery(unknown,caught.value)
    for _ in range(3):
        action=engine.decide(unknown)
        assert action.kind=='key'
        engine.sent(action,unknown)
        clock.advance(9)
    with pytest.raises(NeedsAttention,match='菜单'):engine.decide(unknown)
    assert not engine.begin_recovery(unknown,caught.value)


def test_untrusted_menu_never_authorizes_concede_and_escape_is_bounded(world,targets):
    engine,_,clock,obs=active(world,targets)
    assert engine.begin_recovery(obs,NeedsAttention('failed',recoverable=True))
    engine.sent(engine.decide(obs),obs)
    menu=Observation(State.MENU,.6,False,obs.targets)
    settle(engine,clock,menu)
    action=engine.decide(menu)
    assert action is None or action.kind=='key'
    clock.advance(91)
    with pytest.raises(NeedsAttention,match='90 秒'):engine.decide(menu)


def test_unexpected_confirmation_does_not_authorize_a_click(world,targets):
    engine,_,clock,obs=active(world,targets)
    engine.begin_recovery(obs,NeedsAttention('failed',recoverable=True))
    confirm=Observation(State.CONFIRM,.99,True,obs.targets)
    settle(engine,clock,confirm)
    with pytest.raises(NeedsAttention,match='未预期'):engine.decide(confirm)


def test_menu_retries_count_only_once_and_confirmation_attempts_are_limited(world,targets):
    engine,store,clock,obs=active(world,targets)
    engine.begin_recovery(obs,NeedsAttention('failed',recoverable=True))
    engine.sent(engine.decide(obs),obs)
    menu=Observation(State.MENU,.99,True,obs.targets)
    settle(engine,clock,menu)
    for _ in range(3):
        click=engine.decide(menu)
        engine.sent(click,menu)
        assert engine.recovery_streak==1
        clock.advance(9)
    with pytest.raises(NeedsAttention,match='按钮连续'):engine.decide(menu)
    assert store.recent()[0]['end_reason']=='auto_recovery'


def test_confirm_retry_limit_and_manual_authentication(world,targets):
    engine,_,clock,obs=active(world,targets)
    engine.begin_recovery(obs,NeedsAttention('failed',recoverable=True))
    engine.sent(engine.decide(obs),obs)
    menu=Observation(State.MENU,.99,True,obs.targets)
    settle(engine,clock,menu);engine.sent(engine.decide(menu),menu)
    confirm=Observation(State.CONFIRM,.99,True,obs.targets)
    settle(engine,clock,confirm)
    for _ in range(3):
        engine.sent(engine.decide(confirm),confirm)
        clock.advance(9)
    with pytest.raises(NeedsAttention,match='确认连续'):engine.decide(confirm)
    auth=Observation(State.AUTH,targets=obs.targets)
    settle(engine,clock,auth)
    with pytest.raises(NeedsAttention,match='认证'):engine.decide(auth)


def test_three_consecutive_recoveries_pause_only_after_final_record_is_saved(world,targets):
    engine,store,clock,obs=active(world,targets)
    for index in range(3):
        if index:settle(engine,clock,obs)
        engine.begin_recovery(obs,NeedsAttention('repeated failure',recoverable=True))
        if index<2:
            lobby=finish_recovery(engine,clock,obs)
            assert engine.decide(lobby).target=='lobby_play'
        else:
            with pytest.raises(NeedsAttention,match='连续 3 局'):
                finish_recovery(engine,clock,obs)
    assert engine.completed==3 and engine.match is None
    assert len(store.recent())==3 and all(r['result_status']=='complete' for r in store.recent())


def test_normal_completion_resets_streak_and_max_matches_still_stops(world,targets):
    engine,_,clock,obs=active(world,targets)
    engine.recovery_streak=2
    result=Observation(State.RESULT,.99,True,obs.targets,metrics={'placement':1,'rating':6100})
    settle(engine,clock,result,3)
    lobby=Observation(State.LOBBY,.99,True,obs.targets,metrics={'rating':6100})
    settle(engine,clock,lobby,4)
    assert engine.recovery_streak==0
    settle(engine,clock,obs)
    engine.config.max_matches=2
    engine.begin_recovery(obs,NeedsAttention('failed',recoverable=True))
    lobby=finish_recovery(engine,clock,obs)
    assert engine.done and engine.decide(lobby) is None


def test_missing_result_and_rating_stay_empty_after_verified_lobby(world,targets):
    engine,store,clock,obs=active(world,targets)
    engine.begin_recovery(obs,NeedsAttention('failed',recoverable=True))
    engine.sent(engine.decide(obs),obs)
    menu=Observation(State.MENU,.99,True,obs.targets)
    settle(engine,clock,menu);engine.sent(engine.decide(menu),menu)
    lobby=Observation(State.LOBBY,.99,True,obs.targets,metrics={'rating':None})
    settle(engine,clock,lobby,9)
    record=store.recent()[0]
    assert engine.completed==1 and record['result_status']=='partial'
    assert record['placement'] is None and record['rating_after'] is None


def test_old_database_migration_keeps_all_original_values(tmp_path):
    path=tmp_path/'legacy.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE matches(id TEXT PRIMARY KEY,started_at TEXT NOT NULL,ended_at TEXT,hero_slot INTEGER,end_reason TEXT NOT NULL,placement INTEGER,rating_before INTEGER,rating_after INTEGER,rating_delta INTEGER,result_status TEXT NOT NULL,evidence_path TEXT)')
        db.execute("INSERT INTO matches VALUES('old','2026-10-24',NULL,2,'normal',8,6000,5900,-100,'complete','original.png')")
    for _ in range(2):
        store=Store(path)
        row=store.recent()[0]
        assert row['id']=='old' and row['rating_delta']==-100 and row['evidence_path']=='original.png'
        assert row['recovery_reason']==''
        store.close()


@pytest.mark.parametrize('value',[0,21,1.5,True])
def test_recovery_limit_validation(value):
    with pytest.raises(ValueError):Config(max_consecutive_recoveries=value).validate()


def test_runner_routes_feedback_failure_into_recovery_without_pausing(tmp_path,monkeypatch):
    from bga import runner
    from conftest import Clock
    clock=Clock();actions=[];scene=[State.RECRUIT]
    profile=Profile.load(Path(__file__).resolve().parents[1]/'profiles/pc-integration.json')
    profile.save(tmp_path/'profiles/pc.json')
    class Vision:
        def __init__(self,*args):pass
        def analyze(self,*args):
            metrics={State.RECRUIT:{'gold':10,'upgrade_cost':4,'tavern_tier':3},
                     State.RESULT:{'placement':8,'rating':5900},State.LOBBY:{'rating':5900}}.get(scene[0],{})
            return Observation(scene[0],.99,True,{k:tuple(v) for k,v in profile.points.items()},metrics=metrics,board_count=3)
    class Target:kind='game';hwnd=1
    class Backend:
        def __init__(self,*args):pass
        def screenshot(self,*args):return np.zeros((90,160,3),np.uint8),(0,0,160,90)
        def execute(self,target,action,*args):
            actions.append(action.target or action.key)
            scene[0]={'Escape':State.MENU,'concede':State.CONFIRM,'confirm_concede':State.RESULT,
                      'result_continue':State.LOBBY}.get(action.target or action.key,scene[0])
        def close(self):pass
    monkeypatch.setattr(runner,'Vision',Vision)
    monkeypatch.setattr(runner,'WindowsBackend',Backend)
    monkeypatch.setattr(runner,'pick_window',lambda:Target())
    monkeypatch.setattr(runner.user32,'GetAsyncKeyState',lambda *_:0)
    monkeypatch.setattr(runner,'Engine',lambda *a:Engine(*a,clock=clock))
    monkeypatch.setattr(runner.time,'monotonic',clock)
    worker=runner.Runner(Config(profile_path='profiles/pc.json',observe_only=False,
                               auto_concede_on_error=True,auto_launch=False,auto_adapt_resolution=False,
                               max_matches=1,integration_seconds=150),tmp_path)
    monkeypatch.setattr(worker.stop_event,'wait',lambda seconds:clock.advance(seconds))
    worker.run()
    assert worker.engine.completed==1 and not worker.pause_event.is_set()
    assert actions==['upgrade']*3+['Escape','concede','confirm_concede','result_continue']
    store=Store(tmp_path/'data/matches.sqlite3')
    assert store.recent()[0]['end_reason']=='auto_recovery'
    store.close()
    assert list((tmp_path/'data/screenshots').glob('*automatic_recovery.png'))
    assert not (tmp_path/'data/integration-current/attention.json').exists()


def test_pause_resume_preserves_attempt_budget_and_restored_concession_does_not_shop(world,targets):
    engine,_,clock,obs=active(world,targets)
    engine.begin_recovery(obs,NeedsAttention('failed',recoverable=True))
    engine.sent(engine.decide(obs),obs)
    engine.reset_observation()
    assert engine.recovery['escapes']==1
    engine.match.end_reason='auto_recovery'
    engine.recovery=None
    engine.restore_concession()
    settle(engine,clock,obs)
    assert engine.decide(obs) is None
    confirm=Observation(State.CONFIRM,.99,True,obs.targets)
    settle(engine,clock,confirm)
    assert engine.decide(confirm).target=='confirm_concede'


def test_recovery_timeout_during_unknown_lobby_does_not_requeue(world,targets):
    engine,_,clock,obs=active(world,targets)
    engine.begin_recovery(obs,NeedsAttention('failed',recoverable=True))
    lobby=Observation(State.LOBBY,.6,False,obs.targets)
    settle(engine,clock,lobby)
    clock.advance(91)
    with pytest.raises(NeedsAttention,match='90 秒'):engine.decide(lobby)

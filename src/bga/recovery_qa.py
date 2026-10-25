"""Exercise real recovery decisions and persistence without any game inputs."""
from pathlib import Path
from tempfile import TemporaryDirectory

from .config import Config,Profile
from .engine import Engine,NeedsAttention
from .model import Observation,State
from .store import Store


def verify_error_recovery(root):
    elapsed=[100.0]
    class Log:
        def emit(self,*args,**kwargs):pass
    actions=[]
    with TemporaryDirectory(prefix='recovery-selftest-',dir=Path(root)/'data') as folder:
        store=Store(Path(folder)/'matches.sqlite3')
        try:
            engine=Engine(Config(observe_only=False,auto_concede_on_error=True),store,Log(),clock=lambda:elapsed[0])
            targets={k:tuple(v) for k,v in Profile().points.items()}
            def settle(obs,n=2):
                for _ in range(n):elapsed[0]+=2;engine.observe(obs)
            def send(obs):
                action=engine.decide(obs)
                assert action is not None
                actions.append(action.target or action.key)
                engine.sent(action,obs)
                return action
            recruit=Observation(State.RECRUIT,.99,True,targets,
                                metrics=dict(gold=10,upgrade_cost=4,tavern_tier=3),board_count=3)
            settle(recruit)
            for _ in range(3):
                assert send(recruit).target=='upgrade'
                elapsed[0]+=9
            try:
                engine.decide(recruit)
                raise AssertionError('Failure threshold did not trigger')
            except NeedsAttention as error:
                assert error.recoverable and engine.begin_recovery(recruit,error)
            assert send(recruit).key=='Escape'
            menu=Observation(State.MENU,.99,True,targets)
            settle(menu);assert send(menu).target=='concede'
            confirm=Observation(State.CONFIRM,.99,True,targets)
            settle(confirm);assert send(confirm).target=='confirm_concede'
            settle(recruit);assert engine.decide(recruit) is None
            result=Observation(State.RESULT,.99,True,targets,metrics=dict(placement=8,rating=5900))
            settle(result,4);assert send(result).target=='result_continue'
            lobby=Observation(State.LOBBY,.99,True,targets,metrics=dict(rating=5900))
            settle(lobby,4);assert send(lobby).target=='lobby_play'
            row=store.recent()[0]
            assert row['end_reason']=='auto_recovery' and row['recovery_reason']
            assert row['result_status']=='complete' and engine.completed==1
            return dict(passed=True,actions=actions,end_reason=row['end_reason'],
                        cause_recorded=True,completed=engine.completed,scope='合成观测驱动真实引擎，无游戏操作')
        finally:store.close()

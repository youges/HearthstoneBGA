import pytest

from bga.config import Config, Profile
from bga.engine import Engine
from bga.store import Store


class Clock:
    def __init__(self):self.value=100.0
    def __call__(self):return self.value
    def advance(self,seconds=2):self.value+=seconds


class Log:
    def __init__(self):self.records=[]
    def emit(self,*args,**kwargs):self.records.append((args,kwargs))


@pytest.fixture
def world(tmp_path):
    store=Store(tmp_path/'matches.sqlite3')
    clock=Clock()
    engine=Engine(Config(observe_only=False),store,Log(),clock)
    yield engine,store,clock
    store.close()


def settle(engine,clock,obs,n=2):
    for _ in range(n):
        clock.advance(1)
        engine.observe(obs)


@pytest.fixture
def targets():
    return {k:tuple(v) for k,v in Profile().points.items()}

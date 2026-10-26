"""Mixed-hand regression on the packaged engine, with no game inputs."""
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np

from .config import Config
from .engine import Engine
from .model import Observation,State
from .pc_layout import hand_card_mark
from .store import Store


def verify_mixed_hand(root):
    clock=[100.0]
    class Log:
        def emit(self,*args,**kwargs):pass
    points={'banana':(.40,.93),'minion':(.47,.93),'banana_2':(.54,.93),'board_drop':(.5,.55),'clear_tooltip':(.97,.35)}
    frame=np.random.default_rng(1290).integers(0,256,(864,1536,3),np.uint8)
    marks={n:hand_card_mark(frame,p) for n,p in points.items() if n!='board_drop' and n!='clear_tooltip'}
    def observation(count,board):
        names=['banana','minion','banana_2'][:count]
        return Observation(State.RECRUIT,.99,True,dict(points),metrics={'gold':0,'hand_count':count},
                           board_count=board,hand_minions=names,hand_marks={n:marks[n] for n in names},hand_priority=['minion'])
    with TemporaryDirectory(prefix='mixed-hand-selftest-',dir=Path(root)/'data') as folder:
        store=Store(Path(folder)/'matches.sqlite3')
        try:
            engine=Engine(Config(observe_only=False,inspect_hand_cards=True),store,Log(),clock=lambda:clock[0])
            def settle(obs,n=2):
                for _ in range(n):clock[0]+=2;engine.observe(obs)
            before=observation(2,0);settle(before)
            hover=engine.decide(before);assert hover.target=='minion'
            engine.sent(hover,before)
            tooltip=observation(2,0);tooltip.metrics['hand_card_kind']='minion'
            settle(tooltip);clear=engine.decide(tooltip);assert clear.target=='clear_tooltip'
            engine.sent(clear,tooltip)
            after=observation(3,0)
            settle(after,1);assert engine.decide(after) is None
            settle(after,1);use=engine.decide(after)
            assert use.target=='inspected_hand' and use.destination=='board_drop'
            engine.sent(use,after)
            played=observation(3,1);settle(played)
            assert engine.feedback(use,after,played)
            next_action=engine.decide(played)
            assert engine.pending_hand_play is None and engine.probes_this_turn==0
            assert next_action is not None and next_action.kind=='hover'
            return dict(passed=True,candidate_counts=[2,3,3],board_counts=[0,0,1],
                        selected='minion',two_fresh_frames_required=True,scope='合成手牌和观测驱动真实引擎，无游戏输入')
        finally:store.close()


def verify_chefs_choice(root):
    from .model import Token
    from .vision import classify_hand_text
    clock=[100.0]
    class Log:
        def emit(self,*args,**kwargs):pass
    kind=classify_hand_text([Token('选择一个随从。获取相同类型的另一张随从牌。',.99,(.3,.75,.2,.1)),
                             Token('酒馆',.99,(.38,.92,.05,.03))])
    assert kind=='targeted_acquire'
    targets={'hand_1':(.4,.93),'friendly_target':(.4,.55),'clear_tooltip':(.97,.35),'board_drop':(.5,.55)}
    with TemporaryDirectory(prefix='chef-selftest-',dir=Path(root)/'data') as folder:
        store=Store(Path(folder)/'matches.sqlite3')
        try:
            engine=Engine(Config(observe_only=False,inspect_hand_cards=True),store,Log(),clock=lambda:clock[0])
            def settle(obs,n=2):
                for _ in range(n):clock[0]+=2;engine.observe(obs)
            before=Observation(State.RECRUIT,.99,True,targets,metrics={'gold':0,'hand_count':1,'targeting_arrow':0},board_count=3,hand_minions=['hand_1'])
            settle(before);engine.sent(engine.decide(before),before)
            before.metrics['hand_card_kind']=kind
            settle(before);clear=engine.decide(before);assert clear.target=='clear_tooltip';engine.sent(clear,before)
            settle(before);use=engine.decide(before);assert use.destination=='friendly_target';engine.sent(use,before)
            prompt=Observation(State.RECRUIT,.99,True,targets,metrics={'gold':9,'upgrade_cost':4,'tavern_tier':2,
                'hand_count':0,'targeting_arrow':1,'friendly_target_verified':1},board_count=None)
            settle(prompt);assert not engine.feedback(use,before,prompt)
            target=engine.decide(prompt);assert target.target=='friendly_target';engine.sent(target,prompt)
            after=Observation(State.RECRUIT,.99,True,targets,metrics={'gold':0,'hand_count':1,'targeting_arrow':0},board_count=3,hand_minions=['hand_1'])
            settle(after,1);assert engine.decide(after) is None
            settle(after,1);next_action=engine.decide(after)
            assert engine.pending_hand_play is None and engine.probes_this_turn==0 and next_action.kind=='hover'
            return dict(passed=True,kind=kind,target=target.target,hand_count_unchanged=True,
                        no_upgrade_during_target=True,scope='合成观测驱动真实分类器与引擎，无游戏输入')
        finally:store.close()

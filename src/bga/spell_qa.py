"""Exercise the shipped decision engine; no screenshots or input are involved."""
from .config import Config
from .engine import Engine
from .model import Observation,State


def verify_multiple_spells():
    class Clock:
        value=100.0
        def __call__(self):return self.value
    class Store:
        def save(self,match):pass
    class Log:
        def emit(self,*args,**kwargs):pass
    results=[]
    for arrow in (False,True):
        clock=Clock()
        engine=Engine(Config(observe_only=False,inspect_hand_cards=True),Store(),Log(),clock)
        def settle(obs):
            for _ in range(2):
                clock.value+=2;engine.observe(obs)
        def frame(count,targeting=0):
            names=[f'hand_{i+1}' for i in range(count)]
            points={name:(.5+(i-(count-1)/2)*.055,.93) for i,name in enumerate(names)}
            points.update(friendly_target=(.35,.54),board_drop=(.5,.55))
            return Observation(State.RECRUIT,.99,True,points,
                               metrics={'gold':0,'hand_count':count,'targeting_arrow':targeting},
                               hand_minions=names,board_count=7)
        obs=frame(5);settle(obs);recruit_since=engine.recruit_since
        engine.probes_this_turn=2
        hover=None;casts=0;target_clicks=0
        for count in range(5,0,-1):
            hover=hover or engine.decide(obs)
            assert hover and hover.kind=='hover'
            engine.sent(hover,obs)
            obs.metrics['hand_card_kind']='buff';settle(obs)
            clear=engine.decide(obs);assert clear.target=='clear_tooltip'
            engine.sent(clear,obs);settle(obs)
            use=engine.decide(obs)
            assert use.target=='inspected_hand' and use.destination=='friendly_target'
            engine.sent(use,obs);casts+=1
            if arrow:
                prompt=frame(count-1,1);settle(prompt)
                target=engine.decide(prompt);assert target.target=='friendly_target'
                engine.sent(target,prompt);target_clicks+=1
                clock.value+=2
                assert engine.decide(prompt) is None
            after=frame(count-1);settle(after)
            hover=engine.decide(after)
            assert engine.recruit_since==recruit_since and engine.probes_this_turn==0
            if count>1:assert hover and hover.kind=='hover'
            else:assert hover is None
            obs=after
        results.append({'case':'target_confirmation' if arrow else 'direct_drag',
                        'casts_in_same_turn':casts,'target_clicks':target_clicks,'passed':True})
    return results

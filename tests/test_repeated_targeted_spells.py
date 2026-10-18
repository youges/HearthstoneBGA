"""Keep failed reads bounded while allowing successive verified casts in one turn."""
import pytest

from bga.engine import NeedsAttention
from bga.model import Observation,State
from conftest import settle


def hand(targets,count,arrow=0):
    points=dict(targets,friendly_target=(.35,.54))
    names=[]
    for i in range(count):
        name=f'hand_{i+1}';names.append(name)
        points[name]=(.5+(i-(count-1)/2)*.055,.93)
    return Observation(State.RECRUIT,.99,True,points,
                       metrics={'gold':0,'hand_count':count,'targeting_arrow':arrow},
                       board_count=7,hand_minions=names)


def inspect(engine,clock,obs,hover=None):
    hover=hover or engine.decide(obs)
    assert hover and hover.kind=='hover' and hover.target in obs.hand_minions
    point=obs.targets[hover.target]
    engine.sent(hover,obs)
    obs.metrics['hand_card_kind']='buff'
    settle(engine,clock,obs)
    clear=engine.decide(obs)
    assert clear.target=='clear_tooltip'
    engine.sent(clear,obs)
    settle(engine,clock,obs)
    use=engine.decide(obs)
    assert use.target=='inspected_hand' and use.destination=='friendly_target'
    assert obs.targets['inspected_hand']==point
    engine.sent(use,obs)
    return use


def test_five_buffs_continue_in_one_recruit_phase_after_prior_failed_reads(world,targets):
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    obs=hand(targets,5);settle(engine,clock,obs)
    recruit_since=engine.recruit_since
    # Two earlier reads must not leave only one playable spell this turn.
    engine.probes_this_turn=2
    hover=None
    for count in range(5,0,-1):
        inspect(engine,clock,obs,hover)
        assert engine.probes_this_turn==3 if count==5 else engine.probes_this_turn==1
        after=hand(targets,count-1)
        engine.hand_skipped.add((.5,.93))
        settle(engine,clock,after)
        hover=engine.decide(after)
        assert engine.probes_this_turn==0 and not engine.hand_skipped
        assert engine.recruit_since==recruit_since
        assert engine.pending_hand_play is None
        if count>1:
            assert hover and hover.kind=='hover'
            assert hover.target in after.hand_minions
        else:assert hover is None
        obs=after


@pytest.mark.parametrize('consumed_before_target',[False,True])
def test_target_prompt_finishes_before_inspecting_the_next_shifted_spell(world,targets,consumed_before_target):
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    obs=hand(targets,2);settle(engine,clock,obs)
    engine.probes_this_turn=2
    use=inspect(engine,clock,obs)
    prompt=hand(targets,1 if consumed_before_target else 2,arrow=1)
    settle(engine,clock,prompt)
    assert not engine.feedback(use,obs,prompt)
    select=engine.decide(prompt)
    assert select.kind=='click' and select.target=='friendly_target'
    assert engine.probes_this_turn==3
    engine.sent(select,prompt)
    clock.advance(2)
    assert engine.decide(prompt) is None
    after=hand(targets,1);settle(engine,clock,after)
    hover=engine.decide(after)
    assert hover and hover.kind=='hover'
    assert engine.probes_this_turn==0
    inspect(engine,clock,after,hover)
    empty=hand(targets,0);settle(engine,clock,empty)
    assert engine.decide(empty) is None
    assert engine.pending_hand_play is None


def test_failed_cast_does_not_reset_inspection_budget_or_retry_other_cards(world,targets):
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    obs=hand(targets,2);settle(engine,clock,obs)
    engine.probes_this_turn=2
    inspect(engine,clock,obs)
    unchanged=hand(targets,2);settle(engine,clock,unchanged)
    clock.advance(9)
    assert engine.decide(unchanged) is None
    assert engine.probes_this_turn==3 and engine.failures==1


def test_unknown_cards_still_stop_after_three_inspections(world,targets):
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    obs=hand(targets,5);settle(engine,clock,obs)
    action=None
    for _ in range(3):
        action=action or engine.decide(obs)
        assert action and action.kind=='hover'
        engine.sent(action,obs)
        clock.advance(5)
        clear=engine.decide(obs);assert clear.target=='clear_tooltip'
        engine.sent(clear,obs);settle(engine,clock,obs)
        action=engine.decide(obs)
    assert action is None and engine.probes_this_turn==3


def test_unresolved_arrow_never_starts_second_spell_after_timeout(world,targets):
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    obs=hand(targets,2);settle(engine,clock,obs)
    inspect(engine,clock,obs)
    prompt=hand(targets,1,arrow=1);settle(engine,clock,prompt)
    select=engine.decide(prompt);engine.sent(select,prompt)
    clock.advance(9)
    with pytest.raises(NeedsAttention,match='未完成目标选择'):
        engine.decide(prompt)


def test_effect_choice_then_delayed_arrow_finishes_before_next_spell(world,targets):
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    obs=hand(targets,2);settle(engine,clock,obs)
    engine.probes_this_turn=2
    inspect(engine,clock,obs)
    choice=Observation(State.CHOICE,.99,True,dict(targets),metrics={'choice_targeted':1})
    settle(engine,clock,choice)
    selected=engine.decide(choice);engine.sent(selected,choice)
    waiting=hand(targets,1);settle(engine,clock,waiting)
    assert engine.decide(waiting) is None
    assert engine.probes_this_turn==3
    prompt=hand(targets,1,arrow=1);settle(engine,clock,prompt)
    selected=engine.decide(prompt)
    assert selected.target=='friendly_target'
    engine.sent(selected,prompt)
    remaining=hand(targets,1);settle(engine,clock,remaining)
    hover=engine.decide(remaining)
    assert hover and hover.kind=='hover'
    assert engine.probes_this_turn==0

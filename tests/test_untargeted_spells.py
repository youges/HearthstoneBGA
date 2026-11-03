"""No-target effects, replacement cards and joined Bananas remain distinct."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from bga.engine import NeedsAttention
from bga.model import Observation, State, Token
from bga.vision import Ocr, Vision, classify_hand_text
from bga.config import Profile
from conftest import settle


@pytest.mark.parametrize('text,expected', [
    ('招募新人。随机获得一张等级1的随从牌。', 'untargeted'),
    ('随机获取一张酒馆法术。', 'untargeted'),
    ('随机使一个友方随从获得+2/+2。', 'untargeted'),
    ('使你的随从获得+1/+1。', 'untargeted'),
    ('使你的随从获得圣盾。', 'untargeted'),
    ('钻探原油。你的铸币上限提高1枚。', 'untargeted'),
    ('获取两张酒馆法术。', 'untargeted'),
    ('香蕉。使一个随从获得+1/+1。', 'buff'),
    ('使一个随从获得随机关键字。', 'untargeted'),
    ('选择一个随从。随机获取一张该类型的牌。', 'untargeted'),
    ('随机发现一张随从牌。', 'untargeted'),
    ('选择一个随从。使你的随从获得它的攻击力。', 'untargeted'),
    ('消灭一个友方随从，获得3枚铸币。', 'untargeted'),
    ('发现一个亡语随从。', 'discover'),
    ('使一个随从获得+1/+1，然后发现一张随从牌。', 'discover'),
    ('使你的随从获得+1/+1，然后发现一张随从牌。', 'untargeted'),
    ('招募新人', 'untargeted'),
    ('无法读取效果', 'untargeted'),
])
def test_user_keyword_priority_requires_visible_spell_type(text, expected):
    tokens=[Token(text,.99,(.4,.5,.2,.1)), Token('酒馆',.99,(.45,.8,.1,.04))]
    assert classify_hand_text(tokens)==expected
    assert classify_hand_text(tokens[:1])=='unknown'


def hand(targets, kinds=(30,90), board=7, arrow=0, trusted=True):
    points=dict(targets)
    names=[f'hand_{i}' for i in range(len(kinds))]
    points.update({n:(.45+i*.06,.93) for i,n in enumerate(names)})
    return Observation(State.RECRUIT,.99,trusted,points,
        metrics={'gold':0,'hand_count':len(names),'targeting_arrow':arrow},
        board_count=board,hand_minions=names,
        hand_marks={n:tuple([value]*144) for n,value in zip(names,kinds)})


def cast(engine,clock,obs,kind='untargeted'):
    engine.config.inspect_hand_cards=True
    settle(engine,clock,obs)
    hover=engine.decide(obs); assert hover.kind=='hover'
    engine.sent(hover,obs)
    tooltip=hand(obs.targets,tuple(mark[0] for mark in obs.hand_marks.values()),obs.board_count)
    tooltip.metrics['hand_card_kind']=kind
    settle(engine,clock,tooltip)
    clear=engine.decide(tooltip); assert clear.target=='clear_tooltip'
    engine.sent(clear,tooltip);settle(engine,clock,obs)
    use=engine.decide(obs)
    assert use.target=='inspected_hand' and use.destination=='board_drop'
    engine.sent(use,obs)
    return use


@pytest.mark.parametrize('board',[0,7,None])
def test_no_target_cast_does_not_require_friendly_minion_or_space(world,targets,board):
    engine,_,clock=world
    obs=hand(targets,board=board);obs.targets.pop('friendly_target',None)
    cast(engine,clock,obs)
    assert engine.target_pending_since is None


def test_random_gain_same_hand_size_waits_for_two_clear_frames_then_reads_next_card(world,targets):
    engine,_,clock=world
    before=hand(targets);use=cast(engine,clock,before)
    after=hand(targets,(150,90))
    settle(engine,clock,after,1)
    assert not engine.feedback(use,before,after) and engine.decide(after) is None
    settle(engine,clock,after,1)
    assert engine.feedback(use,before,after)
    action=engine.decide(after)
    assert action.kind=='hover' and engine.pending_hand_play is None
    assert engine.probes_this_turn==0


def test_candidate_count_drop_with_original_spell_still_present_is_not_success(world,targets):
    engine,_,clock=world
    before=hand(targets);use=cast(engine,clock,before)
    after=hand(targets,(30,));settle(engine,clock,after)
    assert not engine.feedback(use,before,after)
    assert engine.decide(after) is None and engine.pending_hand_play


def test_duplicate_spell_consumption_refreshes_budget(world,targets):
    engine,_,clock=world
    before=hand(targets,(30,30,90));use=cast(engine,clock,before)
    after=hand(targets,(30,90));settle(engine,clock,after)
    assert engine.feedback(use,before,after)
    assert engine.decide(after).kind=='hover'
    assert engine.pending_hand_play is None


def test_empty_hand_needs_three_trusted_clear_observations(world,targets):
    engine,_,clock=world
    before=hand(targets,(30,));use=cast(engine,clock,before)
    after=hand(targets,())
    settle(engine,clock,after,2)
    assert not engine.feedback(use,before,after)
    settle(engine,clock,after,1)
    assert engine.feedback(use,before,after)
    engine.decide(after);assert engine.pending_hand_play is None


def test_untrusted_or_arrow_frame_resets_completion_counter(world,targets):
    engine,_,clock=world
    before=hand(targets);use=cast(engine,clock,before)
    after=hand(targets,(150,90));settle(engine,clock,after,1)
    settle(engine,clock,hand(targets,(150,90),trusted=False),1)
    settle(engine,clock,after,1)
    assert not engine.feedback(use,before,after)
    arrow=hand(targets,(150,90),arrow=1);settle(engine,clock,arrow)
    assert not engine.feedback(use,before,arrow)
    clock.advance(9)
    with pytest.raises(NeedsAttention,match='意外目标箭头'):engine.decide(arrow)


def test_discover_chooses_then_refreshes_even_if_hand_size_is_unchanged(world,targets):
    engine,_,clock=world
    before=hand(targets);use=cast(engine,clock,before,'discover')
    choice=Observation(State.CHOICE,.99,True,dict(targets),metrics={'choice_targeted':0})
    settle(engine,clock,choice)
    assert engine.feedback(use,before,choice)
    select=engine.decide(choice);assert select.target=='choice_1'
    engine.sent(select,choice)
    after=hand(targets,(150,90));settle(engine,clock,after)
    assert engine.decide(after).kind=='hover' and engine.pending_hand_play is None


def test_banana_with_unknown_board_waits_for_verified_target(world,targets):
    engine,_,clock=world
    before=hand(targets,board=None);use=cast(engine,clock,before,'buff')
    prompt=hand(targets,board=None,arrow=1);settle(engine,clock,prompt)
    assert engine.decide(prompt) is None
    prompt.metrics['friendly_target_verified']=1
    prompt.targets['friendly_target']=(.4,.54);settle(engine,clock,prompt)
    target=engine.decide(prompt);assert target.target=='friendly_target'
    engine.sent(target,prompt)
    # A previously missed card can replace the consumed banana candidate.
    after=hand(targets,(150,90),board=None);settle(engine,clock,after)
    assert engine.feedback(use,before,after)
    assert engine.decide(after).kind=='hover' and engine.pending_hand_play is None


def test_no_target_unknown_effect_still_handles_a_real_discover_screen(world,targets):
    engine,_,clock=world
    before=hand(targets);use=cast(engine,clock,before)
    choice=Observation(State.CHOICE,.99,True,dict(targets))
    settle(engine,clock,choice)
    assert engine.feedback(use,before,choice)
    select=engine.decide(choice);assert select.target=='choice_1'
    engine.sent(select,choice)
    after=hand(targets,(150,90));settle(engine,clock,after)
    assert engine.decide(after).kind=='hover' and engine.pending_hand_play is None


def test_purchase_glow_change_requires_a_new_type_read_before_cast(world,targets):
    targets['friendly_target']=(.4,.54)
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    before=hand(targets);settle(engine,clock,before)
    hover=engine.decide(before);engine.sent(hover,before)
    tooltip=hand(targets);tooltip.metrics['hand_card_kind']='untargeted'
    settle(engine,clock,tooltip);clear=engine.decide(tooltip);engine.sent(clear,tooltip)
    changed=hand(targets,(150,90));settle(engine,clock,changed);clock.advance(7)
    retry=engine.decide(changed)
    assert retry.kind=='hover' and engine.hand_probe is None
    engine.sent(retry,changed)
    reread=hand(targets,(150,90));reread.metrics['hand_card_kind']='buff'
    settle(engine,clock,reread);clear=engine.decide(reread);engine.sent(clear,reread)
    settle(engine,clock,changed);use=engine.decide(changed)
    assert use.target=='inspected_hand' and use.destination=='friendly_target'
    assert changed.metrics['precast_hand_kind']=='buff'


def test_steal_same_hand_size_resets_inspection_budget_after_shop_feedback(world,targets):
    engine,_,clock=world
    before=hand(targets);before.metrics['shop_card_count']=3
    use=cast(engine,clock,before,'steal')
    after=hand(targets,(150,90));after.metrics['shop_card_count']=2
    settle(engine,clock,after)
    assert engine.feedback(use,before,after)
    assert engine.decide(after).kind=='hover' and engine.pending_hand_play is None
    assert engine.probes_this_turn==0


ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('size',[(1536,864),(1920,1080),(1280,720)])
def test_live_joined_bananas_have_multiple_stable_hover_candidates(size):
    folder=ROOT/'dist/HearthstoneBGA/data/screenshots'
    path=folder/'1793712841919571700_before_hand_green_3.png'
    if not path.exists():pytest.skip('Private live screenshot is not distributed')
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,Ocr())
    image=cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR)
    obs=vision.analyze(cv2.resize(image,size,interpolation=cv2.INTER_AREA))
    assert obs.trusted and obs.state==State.RECRUIT
    assert len(obs.hand_minions)>=3
    assert any(n.startswith('hand_joined_') for n in obs.hand_minions)
    for n in obs.hand_minions:
        x,y=obs.targets[n]
        assert .32<x<.64 and .89<y<.97 and n in obs.hand_marks

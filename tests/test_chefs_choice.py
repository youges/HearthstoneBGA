"""Chef's Choice must acquire a minion only after selecting a legal target."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from bga.config import Profile
from bga.model import Observation,State,Token
from bga.pc_layout import highlighted_shop_target
from bga.vision import Vision,classify_hand_text
from conftest import settle

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('description,expected',[
    ('选择一个随从。获取相同类型的另一张随从牌。','targeted_acquire'),
    ('选择一个随从。获得同类型的另一张随从牌。','targeted_acquire'),
    ('主厨甄选，文字未读取完整','unknown'),
    ('选择一个随从。消灭它，获取相同类型的另一张随从牌。','unknown'),
    ('选择一个敌方随从。获取相同类型的另一张随从牌。','unknown'),
    ('发现一个随从。','discover'),
    ('使一个随从获得+3/+3。','buff'),
])
def test_spell_description_distinguishes_targeted_acquisition(description,expected):
    tokens=[Token(description,.99,(.3,.75,.2,.1)),Token('酒馆',.99,(.38,.92,.05,.03))]
    assert classify_hand_text(tokens)==expected


def ready_spell(engine,clock,targets,board=3):
    engine.config.inspect_hand_cards=True
    t=dict(targets,hand_1=(.4,.93),friendly_target=(.39,.55),shop_1=(.44,.37))
    obs=Observation(State.RECRUIT,.99,True,t,metrics={'gold':0,'hand_count':1,'targeting_arrow':0},
                    board_count=board,hand_minions=['hand_1'],shop_minions=['shop_1'])
    settle(engine,clock,obs)
    engine.sent(engine.decide(obs),obs)
    obs.metrics['hand_card_kind']='targeted_acquire'
    settle(engine,clock,obs)
    clear=engine.decide(obs);assert clear.target=='clear_tooltip';engine.sent(clear,obs)
    settle(engine,clock,obs)
    use=engine.decide(obs)
    return obs,use


def test_owned_chef_arrow_selects_verified_minion_without_ocr_hint(world,targets):
    engine,_,clock=world
    before,use=ready_spell(engine,clock,targets)
    assert use.destination=='friendly_target'
    engine.sent(use,before)
    prompt=Observation(State.RECRUIT,.99,True,before.targets,
                       metrics={'gold':9,'upgrade_cost':4,'tavern_tier':2,'targeting_arrow':1,
                                'friendly_target_verified':1,'hand_count':0},board_count=None)
    settle(engine,clock,prompt)
    assert not engine.feedback(use,before,prompt)
    action=engine.decide(prompt)
    assert action.target=='friendly_target' and action.kind=='click'


def test_acquired_card_replacing_spell_does_not_require_a_smaller_hand(world,targets):
    engine,_,clock=world
    before,use=ready_spell(engine,clock,targets)
    engine.sent(use,before)
    prompt=Observation(State.RECRUIT,.99,True,before.targets,
                       metrics={'targeting_arrow':1,'friendly_target_verified':1,'hand_count':0},board_count=None)
    settle(engine,clock,prompt)
    select=engine.decide(prompt);engine.sent(select,prompt)
    after=Observation(State.RECRUIT,.99,True,before.targets,
                      metrics={'gold':0,'targeting_arrow':0,'hand_count':1},board_count=3,hand_minions=['hand_1'])
    settle(engine,clock,after,1);assert engine.decide(after) is None
    settle(engine,clock,after,1)
    next_action=engine.decide(after)
    assert engine.pending_hand_play is None and engine.target_pending_since is None
    assert engine.probes_this_turn==0 and next_action.kind=='hover'


def test_direct_target_drag_can_finish_using_visual_spell_consumption(world,targets):
    engine,_,clock=world
    before,use=ready_spell(engine,clock,targets)
    before.hand_marks['inspected_hand']=(20,)*144
    engine.sent(use,before)
    after=Observation(State.RECRUIT,.99,True,before.targets,
                      metrics={'gold':0,'targeting_arrow':0,'hand_count':1},board_count=3,
                      hand_minions=['hand_1'],hand_marks={'hand_1':(150,)*144})
    settle(engine,clock,after,1);assert engine.decide(after) is None
    settle(engine,clock,after,1)
    assert engine.feedback(use,before,after)
    engine.decide(after)
    assert engine.pending_hand_play is None and engine.target_pending_since is None


def test_empty_board_chef_can_target_a_verified_tavern_minion(world,targets):
    engine,_,clock=world
    before,use=ready_spell(engine,clock,targets,board=0)
    assert use.destination=='shop_1'
    engine.sent(use,before)
    prompt=Observation(State.RECRUIT,.99,True,dict(before.targets,shop_spell_target=(.44,.37)),
                       metrics={'targeting_arrow':1,'shop_target_verified':1,'hand_count':0},board_count=0)
    settle(engine,clock,prompt)
    assert engine.decide(prompt).target=='shop_spell_target'


def test_buff_cannot_reuse_chef_shop_target_permission(world,targets):
    engine,_,clock=world
    engine.pending_hand_play={'precast_hand_kind':'buff'}
    prompt=Observation(State.RECRUIT,.99,True,dict(targets,shop_spell_target=(.44,.37)),
                       metrics={'targeting_arrow':1,'shop_target_verified':1},board_count=0)
    settle(engine,clock,prompt)
    assert engine.decide(prompt) is None


def test_chef_uses_shop_highlight_when_friendly_minions_are_not_legal(world,targets):
    engine,_,clock=world
    engine.pending_hand_play={'precast_hand_kind':'targeted_acquire'}
    prompt=Observation(State.RECRUIT,.99,True,dict(targets,friendly_target=(.4,.55),shop_spell_target=(.44,.37)),
                       metrics={'targeting_arrow':1,'shop_target_verified':1},board_count=3)
    settle(engine,clock,prompt)
    assert engine.decide(prompt).target=='shop_spell_target'


def test_unknown_targeting_arrow_blocks_unrelated_upgrades(world,targets):
    engine,_,clock=world
    obs=Observation(State.RECRUIT,.99,True,targets,metrics={'gold':10,'upgrade_cost':4,
                    'tavern_tier':2,'targeting_arrow':1},board_count=3,shop_minions=['shop_1'])
    settle(engine,clock,obs)
    assert engine.decide(obs) is None


def test_smaller_card_below_selected_footer_cannot_supply_discover_text():
    class FakeOCR:
        def tokens(self,_):return []
    v=Vision(Profile(),ROOT,FakeOCR());v.inspect_point=(.4,.93)
    obs=Observation(State.RECRUIT,tokens=[Token('未知效果文字',.99,(.33,.8,.15,.06)),
        Token('酒馆',.99,(.38,.92,.05,.03)),Token('发动（2）：发现一张随从牌',.99,(.42,.976,.12,.015))])
    v.inspect_context(obs,np.zeros((1080,1920,3),np.uint8))
    assert obs.metrics['hand_card_kind']=='unknown'


def incident(name):
    path=ROOT/'data/qa-20261025-chefs-choice'/name
    if not path.exists():pytest.skip('Private Chef spell screenshots are not distributed')
    return cv2.imdecode(np.fromfile(path,np.uint8),1)


class NoOCR:
    def tokens(self,_):return []
    def recognize_line(self,_):return []


@pytest.mark.parametrize('name',['1792936044901824400_after_inspected_hand.png',
                                 '1792936166998942000_after_inspected_hand.png'])
@pytest.mark.parametrize('width',[1280,1536,1920,2560])
def test_actual_chef_prompt_has_legal_target_and_never_upgrades(world,name,width):
    frame=cv2.resize(incident(name),(width,width*9//16),interpolation=cv2.INTER_AREA)
    v=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,NoOCR())
    obs=v.analyze(frame)
    assert obs.state==State.RECRUIT and obs.trusted and obs.metrics['targeting_arrow']==1
    assert obs.metrics['friendly_target_verified']==1
    assert obs.metrics['shop_target_verified']==1
    fx,fy=obs.targets['friendly_target'];sx,sy=obs.targets['shop_spell_target']
    assert .32<fx<.66 and .51<fy<.59 and .29<sx<.64 and .34<sy<.40
    engine,_,clock=world
    engine.pending_hand_play={'precast_hand_kind':'targeted_acquire','precast_hand_count':3}
    settle(engine,clock,obs)
    assert engine.decide(obs).target=='friendly_target'


def test_actual_chef_tooltip_is_targeted_acquisition_not_discover():
    frame=incident('1792936151089379600_before_clear_tooltip.png')
    v=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT)
    v.inspect_point=(.404296875,.9293981481481481)
    obs=v.analyze(frame)
    assert obs.metrics['hand_card_kind']=='targeted_acquire'


def test_frozen_selftest_recipe_covers_target_and_unchanged_hand_count(tmp_path):
    from bga.hand_qa import verify_chefs_choice
    (tmp_path/'data').mkdir()
    assert verify_chefs_choice(tmp_path)['passed']

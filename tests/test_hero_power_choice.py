"""Post-entry power choices block shopping and keep the current hero record."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from bga.config import Profile
from bga.engine import NeedsAttention
from bga.model import Observation, State, Token
from bga.pc_layout import hero_power_choice_point
from bga.vision import Vision
from conftest import settle

ROOT=Path(__file__).resolve().parents[1]


class NoOCR:
    def tokens(self,_):return []
    def recognize_line(self,_):return []


def image(name='20261024-hero-power-hover'):
    path=ROOT/'data/calibration'/f'{name}.png'
    if not path.exists():pytest.skip('Private game screenshot is not distributed')
    return cv2.imdecode(np.fromfile(path,np.uint8),cv2.IMREAD_COLOR)


def vision(profile=None,ocr=None):
    return Vision(profile or Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,ocr or NoOCR())


@pytest.mark.parametrize('name',['20261021-hero-power-choice','20261024-hero-power-hover'])
@pytest.mark.parametrize('width',[960,1280,1536,1920,2560,3840])
def test_actual_power_cards_with_and_without_hover(width,name):
    obs=vision().analyze(cv2.resize(image(name),(width,width*9//16),interpolation=cv2.INTER_AREA))
    assert obs.state==State.CHOICE and obs.trusted
    x,y=obs.targets['choice_1']
    assert .28<x<.32 and .42<y<.48
    assert obs.metrics=={'choice_kind':'hero_power','choice_targeted':0}
    assert obs.board_count is None and not obs.shop_minions


def outlined_cards(xs=(330,640,950),width=250,height=205,solid=False):
    frame=np.full((864,1536,3),30,np.uint8)
    for x in xs:
        cv2.rectangle(frame,(x,285),(x+width,285+height),(0,255,0),-1 if solid else 7)
    return frame


@pytest.mark.parametrize('xs',[(330,640,950),(480,800)])
def test_two_or_three_outlines_locate_the_actual_left_card(xs):
    point=hero_power_choice_point(outlined_cards(xs))
    assert point==pytest.approx(((xs[0]+125)/1536,387.5/864),abs=.004)


@pytest.mark.parametrize('width,height,solid',[(150,205,False),(330,205,False),
                                             (250,90,False),(250,205,True)])
def test_incomplete_or_filled_green_shapes_do_not_supply_a_click(width,height,solid):
    assert hero_power_choice_point(outlined_cards((330,),width,height,solid)) is None


def test_one_remaining_upright_edge_does_not_supply_a_click():
    frame=outlined_cards((330,))
    frame[:,550:]=30
    assert hero_power_choice_point(frame) is None


def test_verified_title_during_card_animation_blocks_tavern_actions(world):
    frame=image()
    frame[280:755,390:1510]=30
    obs=vision().analyze(frame)
    assert obs.state==State.CHOICE and not obs.trusted
    assert 'choice_1' not in obs.targets
    engine,_,clock=world
    settle(engine,clock,obs)
    assert engine.decide(obs) is None


def test_targeting_words_on_a_power_describe_future_use():
    class PowerOCR(NoOCR):
        def tokens(self,_):return [Token('选择一个随从，使其获得+3/+3',.99,(.25,.53,.15,.1))]
    obs=vision(ocr=PowerOCR()).analyze(image())
    assert obs.trusted and obs.metrics['choice_targeted']==0


def test_power_text_without_a_visual_title_is_not_authorization():
    class PowerOCR(NoOCR):
        def tokens(self,_):return [Token('抉择 选择英雄技能',.99,(.4,.12,.2,.04))]
    frame=outlined_cards()
    obs=vision(ocr=PowerOCR()).analyze(frame)
    assert not obs.trusted


def test_missing_selection_calibration_cannot_use_the_dynamic_point(world):
    profile=Profile.load(ROOT/'profiles/pc-integration.json')
    profile.verified_points.remove('choice_1')
    obs=vision(profile).analyze(image())
    assert obs.state==State.CHOICE and obs.trusted and 'choice_1' not in obs.targets
    engine,_,clock=world
    settle(engine,clock,obs)
    with pytest.raises(NeedsAttention,match='choice_1'):engine.decide(obs)


def test_power_choice_preserves_initial_hero_and_waits_before_recruiting(world,targets):
    engine,store,clock=world
    hero=Observation(State.HERO,.99,True,targets,available_heroes=[2])
    settle(engine,clock,hero)
    match_id=engine.match.id
    choose=engine.decide(hero)
    engine.sent(choose,hero)
    hero.metrics['hero_selected_slot']=2
    settle(engine,clock,hero)
    confirm=engine.decide(hero)
    assert confirm.target=='hero_confirm'
    engine.sent(confirm,hero)
    choice=vision().analyze(image())
    settle(engine,clock,choice)
    action=engine.decide(choice)
    assert action.target=='choice_1' and action.label=='选择英雄技能'
    engine.sent(action,choice)
    settle(engine,clock,choice)
    assert engine.decide(choice) is None
    assert engine.target_pending_since is None
    recruit=Observation(State.RECRUIT,.99,True,targets,
                        metrics={'gold':3,'upgrade_cost':5,'tavern_tier':1},
                        board_count=0,shop_minions=['shop_1'])
    assert engine.feedback(action,choice,recruit)
    settle(engine,clock,recruit)
    assert engine.decide(recruit).target=='shop_1'
    assert engine.match.id==match_id and engine.match.hero_slot==2
    assert len(store.recent())==1


@pytest.mark.parametrize('name',['hero','recruit-empty','program-two-choice','program-discover-three',
                                '20261022-two-spell-choice','20261024-event-quests-popup'])
def test_existing_screens_are_not_reclassified_as_power_selection(name):
    obs=vision().analyze(image(name))
    assert obs.metrics.get('choice_kind')!='hero_power'

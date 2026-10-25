"""Untitled battlecry choices must block tavern actions until dismissed."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from bga.config import Profile
from bga.engine import NeedsAttention
from bga.model import Observation, State, Token
from bga.pc_layout import two_spell_choice_cards
from bga.vision import Vision
from conftest import settle


ROOT=Path(__file__).resolve().parents[1]


class NoOCR:
    def tokens(self,image):return []
    def recognize_line(self,image):return []


def outline_frame(boxes=((433,251,269,296),(830,253,261,295)),solid=False):
    frame=np.full((864,1536,3),20,np.uint8)
    for x,y,w,h in boxes:
        cv2.rectangle(frame,(x,y),(x+w-1,y+h-1),(0,255,0),-1 if solid else 7)
    return frame


def test_aligned_selectable_outlines_supply_actual_card_centers():
    points=two_spell_choice_cards(outline_frame())
    assert points is not None
    assert points[0]==pytest.approx((567.5/1536,399/864),abs=.005)
    assert points[1]==pytest.approx((960.5/1536,400.5/864),abs=.005)


@pytest.mark.parametrize('boxes,solid',[
    (((433,251,269,296),),False),  # a single enlarged hand tooltip
    (((433,251,269,296),(830,310,261,295)),False),  # mismatched rows
    (((350,251,269,296),(830,253,261,295)),False),  # wrong card spacing
    (((433,251,160,296),(830,253,261,295)),False),  # incomplete outline
    (((433,251,269,296),(830,253,261,295)),True),  # green artwork alone
    (((433,251,269,296),(830,253,261,295),(700,253,100,295)),False),
])
def test_partial_or_inconsistent_shapes_do_not_authorize_a_choice(boxes,solid):
    assert two_spell_choice_cards(outline_frame(boxes,solid)) is None


def test_two_art_patches_without_upright_edges_are_rejected():
    frame=outline_frame()
    frame[295:520,420:490]=20
    frame[295:520,665:715]=20
    assert two_spell_choice_cards(frame) is None


def incident(name='20261022-two-spell-choice'):
    path=ROOT/'data/calibration'/f'{name}.png'
    if not path.exists():pytest.skip('Private game screenshot is not distributed')
    return cv2.imdecode(np.fromfile(path,np.uint8),cv2.IMREAD_COLOR)


@pytest.mark.parametrize('width',[1280,1536,1920,2560])
@pytest.mark.parametrize('name',['20261022-two-spell-choice','20261022-two-spell-choice-first',
                                 '20261022-two-spell-choice-retry1','20261022-two-spell-choice-retry2'])
def test_real_tenth_match_is_choice_over_visible_recruit_header(width,name):
    frame=incident(name)
    frame=cv2.resize(frame,(width,round(frame.shape[0]*width/frame.shape[1])),interpolation=cv2.INTER_AREA)
    result=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,NoOCR()).analyze(frame)
    assert result.state==State.CHOICE and result.trusted
    assert result.metrics['choice_cards']==2
    assert .34<result.targets['choice_1'][0]<.40
    assert .43<result.targets['choice_1'][1]<.50
    assert 'gold' not in result.metrics and 'upgrade_cost' not in result.metrics


def synthetic_vision(tmp_path):
    profile=Profile(layout_mode='pc_v1',verified_points=['choice_1'])
    # A real visual header match remains a prerequisite for this extra detector.
    frame=outline_frame()
    patch=np.random.default_rng(44).integers(0,255,(30,70,3),np.uint8)
    frame[80:110,700:770]=patch
    cv2.imencode('.png',patch)[1].tofile(tmp_path/'header.png')
    spec={'file':'header.png','box':[700/1536,80/864,70/1536,30/864],
          'frame_size':[1536,864],'threshold':.94}
    profile.anchors={'recruit':spec}
    return frame,profile,Vision(profile,tmp_path,NoOCR())


def test_visual_choice_is_handled_before_any_more_upgrades(world,targets,tmp_path):
    frame,profile,vision=synthetic_vision(tmp_path)
    engine,_,clock=world
    ordinary=Observation(State.RECRUIT,.99,True,targets,
                         metrics={'gold':10,'upgrade_cost':6,'tavern_tier':3},board_count=6)
    settle(engine,clock,ordinary)
    attempted=engine.decide(ordinary)
    assert attempted.target=='upgrade'
    engine.sent(attempted,ordinary)
    choice=vision.analyze(frame)
    assert choice.state==State.CHOICE and choice.trusted
    settle(engine,clock,choice)
    select=engine.decide(choice)
    assert select.target=='choice_1' and select.kind=='click'
    assert choice.targets[select.target]==pytest.approx((.37,.46),abs=.01)
    engine.sent(select,choice)
    settle(engine,clock,choice)
    assert engine.decide(choice) is None  # waiting for choice feedback
    # Shop/upgrade actions become possible only after the overlay is gone.
    settle(engine,clock,ordinary)
    assert engine.decide(ordinary).target=='upgrade'


@pytest.mark.parametrize('x,y,expected',[(.50,.94,0),(.625,.55,0),(.37,.55,1)])
def test_target_requirement_reads_only_the_option_being_selected(tmp_path,x,y,expected):
    frame,profile,vision=synthetic_vision(tmp_path)
    class TargetText(NoOCR):
        def tokens(self,image):
            return [Token('使一个随从获得+3/+3',.99,(x-.04,y-.01,.08,.02))]
    vision.ocr=TargetText()
    obs=vision.analyze(frame)
    assert obs.state==State.CHOICE and obs.trusted
    assert obs.metrics['choice_targeted']==expected


def test_outline_pair_without_a_verified_tavern_is_not_trusted(tmp_path):
    frame,profile,vision=synthetic_vision(tmp_path)
    frame[80:110,700:770]=20
    assert not vision.analyze(frame).trusted
    profile.layout_mode='manual'
    assert not vision.analyze(frame).trusted


def test_choice_still_blocks_upgrades_without_a_calibrated_selection(world,tmp_path):
    frame,profile,vision=synthetic_vision(tmp_path)
    profile.verified_points=[]
    choice=vision.analyze(frame)
    assert choice.state==State.CHOICE and 'choice_1' not in choice.targets
    engine,_,clock=world
    settle(engine,clock,choice)
    with pytest.raises(NeedsAttention,match='choice_1'):
        engine.decide(choice)


@pytest.mark.parametrize('modal',[State.MENU,State.CONFIRM,State.NOTICE])
def test_confirmed_blocking_modal_keeps_priority_over_card_outlines(tmp_path,modal):
    frame,profile,vision=synthetic_vision(tmp_path)
    profile.anchors[modal.value]=profile.anchors['recruit']
    result=vision.analyze(frame)
    assert result.state==modal and result.trusted


@pytest.mark.parametrize('name',[
    '20261022-before-two-spell-choice','program-generic-minion-tooltip',
    'program-locked-hand','recruit-empty','program-recruit-three','program-tier6',
])
def test_real_recruit_and_hover_frames_are_not_new_choices(name):
    frame=incident(name)
    assert two_spell_choice_cards(frame) is None
    result=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,NoOCR()).analyze(frame)
    assert result.state!=State.CHOICE

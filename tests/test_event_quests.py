"""Login event quests use the existing modal dismissal and feedback path."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from bga.config import Profile
from bga.engine import NeedsAttention
from bga.model import State, Token
from bga.vision import Vision
from conftest import settle


ROOT=Path(__file__).resolve().parents[1]


class NoOCR:
    def tokens(self,_):return []
    def recognize_line(self,_):return []


def frame(name='20261024-event-quests-popup'):
    path=ROOT/'data/calibration'/f'{name}.png'
    if not path.is_file():pytest.skip('Private game screenshot is not distributed')
    return cv2.imdecode(np.fromfile(path,np.uint8),cv2.IMREAD_COLOR)


@pytest.mark.parametrize('profile_name',['pc-integration','live-partial'])
@pytest.mark.parametrize('width',[960,1280,1536,1920,2560,3840])
def test_event_quests_title_authorizes_only_the_calibrated_dismissal(profile_name,width):
    profile=Profile.load(ROOT/'profiles'/f'{profile_name}.json')
    image=cv2.resize(frame(),(width,width*9//16),interpolation=cv2.INTER_AREA)
    obs=Vision(profile,ROOT,NoOCR()).analyze(image)
    assert obs.state==State.NOTICE and obs.trusted
    assert obs.targets['notice_close']==tuple(profile.points['notice_close'])
    assert obs.metrics=={} and obs.board_count is None


def test_changing_quest_rewards_and_progress_does_not_change_the_notice():
    image=frame()
    image[345:735,610:1290]=np.random.default_rng(47).integers(0,256,(390,680,3),dtype=np.uint8)
    obs=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,NoOCR()).analyze(image)
    assert obs.state==State.NOTICE and obs.trusted


def test_quest_text_without_the_visual_title_cannot_authorize_input():
    class QuestOCR(NoOCR):
        def tokens(self,_):return [Token('你的活动任务 古神低语 每日任务',.99,(.4,.2,.2,.05))]
    image=frame()
    image[190:285,690:1230]=0
    obs=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,QuestOCR()).analyze(image)
    assert not obs.trusted and obs.state==State.UNKNOWN


@pytest.mark.parametrize('name',['entry','main','hero','recruit-empty','program-recruit-three',
                                'program-generic-minion-tooltip','program-two-choice',
                                'program-discover-three','20261022-two-spell-choice'])
def test_existing_game_screens_are_not_event_notices(name):
    obs=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,NoOCR()).analyze(frame(name))
    assert obs.state!=State.NOTICE


def test_quest_popup_waits_for_stable_frames_and_does_not_start_a_match(world):
    engine,store,clock=world
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,NoOCR())
    popup=vision.analyze(frame())
    engine.observe(popup)
    assert engine.decide(popup) is None
    settle(engine,clock,popup)
    close=engine.decide(popup)
    assert close.kind=='click' and close.target=='notice_close'
    assert engine.match is None and store.recent()==[]
    engine.sent(close,popup)
    settle(engine,clock,popup)
    assert engine.decide(popup) is None
    main=vision.analyze(frame('main'))
    assert main.state==State.MAIN and main.trusted
    assert engine.feedback(close,popup,main)
    settle(engine,clock,main)
    assert engine.decide(main).target=='main_modes'
    assert engine.match is None and store.recent()==[]


def test_missing_dismissal_calibration_blocks_the_click(world):
    engine,_,clock=world
    profile=Profile.load(ROOT/'profiles/pc-integration.json')
    profile.verified_points.remove('notice_close')
    popup=Vision(profile,ROOT,NoOCR()).analyze(frame())
    assert popup.state==State.NOTICE and popup.trusted
    settle(engine,clock,popup)
    with pytest.raises(NeedsAttention,match='notice_close'):
        engine.decide(popup)

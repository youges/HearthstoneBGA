"""The bartender skin must not hide an otherwise stable recruit screen."""
from pathlib import Path
import cv2
import numpy as np
import pytest
from bga.config import Profile
from bga.model import State
from bga.vision import Vision

ROOT=Path(__file__).resolve().parents[1]
QA=ROOT/'data/qa-20261027-full-hand'

class NoOCR:
    def tokens(self,_):return []
    def recognize_line(self,_):return []

def image(name):
    p=QA/name
    if not p.exists():pytest.skip('Private bartender incident screenshots are not distributed')
    return cv2.imdecode(np.fromfile(p,np.uint8),1)

@pytest.mark.parametrize('width',[960,1280,1536,1920,2560])
def test_real_changed_bartender_is_trusted_recruit_without_ocr(width):
    frame=image('1793076778776578800-latest.png')
    frame=cv2.resize(frame,(width,width*9//16),interpolation=cv2.INTER_AREA)
    profile=Profile.load(ROOT/'profiles/pc-integration.json')
    vision=Vision(profile,ROOT,NoOCR())
    primary={k:v for k,v in profile.anchors['recruit'].items() if k!='alternatives'}
    assert vision.match(frame,primary)<primary['threshold']
    obs=vision.analyze(frame)
    assert obs.state==State.RECRUIT and obs.trusted
    assert obs.board_count==3 and obs.hand_minions

@pytest.mark.parametrize('name',['1793076343557385600_state_unknown.png',
    '1793076564246942600_state_unknown.png','1793076700606368200_state_unknown.png'])
def test_blurred_recruit_transition_does_not_authorize_actions(name):
    obs=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,NoOCR()).analyze(image(name))
    assert obs.state==State.UNKNOWN and not obs.trusted

def test_small_public_control_template_contains_no_bartender_or_price_digit():
    profile=Profile.load(ROOT/'profiles/pc-integration.json')
    spec=profile.anchors['recruit']['alternatives'][0]
    patch=cv2.imdecode(np.fromfile(ROOT/spec['file'],np.uint8),1)
    assert patch.shape[:2]==(57,63) and spec['threshold']==.96
    assert spec['box'][0]>.56 and spec['box'][1]>.16

from pathlib import Path
import cv2
import numpy as np
import pytest

from bga.config import Profile
from bga.model import Token
from bga.vision import Ocr,Vision,gold_fraction

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('text,expected',[
    ('7/7',(7,7)),('7:7',(7,7)),('7.7',(7,7)),('0/10',(0,10)),
    ('13/10',(13,10)),('L/L',None),('717',None),('77',None),
    ('31/10',None),('7/99',None),('7/0',None),('gold7/7',None)])
def test_gold_fraction_requires_two_bounded_numbers(text,expected):
    assert gold_fraction(text)==expected

@pytest.mark.parametrize('readings,expected',[
    (['L/L','717','7:7','7.7'],7),
    (['717','7/7','L/L','7.7'],7),
    (['L/L','7/7','7/8','7.7'],None),
    (['L/L','7/7','L/L','77'],None),
    (['L/L','L/L','L/L','L/L'],None),
    (['L/L','77','77','77'],None)])
def test_fallback_needs_two_matching_full_fractions(readings,expected,tmp_path):
    class SequenceOCR:
        def __init__(self):self.responses=iter(readings)
        def recognize_line(self,image):return [Token(next(self.responses),.99,(0,0,1,1))]
    profile=Profile(regions={'gold':[0,0,1,1]},verified_regions=['gold'])
    image=np.zeros((25,60,3),dtype=np.uint8)
    assert Vision(profile,tmp_path,SequenceOCR()).read_metric(image,'gold')==expected

@pytest.fixture(scope='module')
def real_ocr():return Ocr()

@pytest.mark.parametrize('width',[1280,1536,1920,2560])
def test_saved_seven_gold_failure_at_multiple_sizes(real_ocr,width):
    path=ROOT/'data/public-0.2.1-live-evidence/gold-unreadable.png'
    if not path.exists():pytest.skip('Local game evidence is not distributed')
    image=cv2.imdecode(np.fromfile(path,np.uint8),cv2.IMREAD_COLOR)
    image=cv2.resize(image,(width,round(image.shape[0]*width/image.shape[1])),interpolation=cv2.INTER_AREA)
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,real_ocr)
    assert vision.read_metric(image,'gold')==7

@pytest.mark.parametrize('name,expected',[
    ('20261017-gold-seven-raw.png',1),('20261017-gold-seven.png',7)])
def test_existing_other_gold_counters_still_read(real_ocr,name,expected):
    path=ROOT/'data/calibration'/name
    if not path.exists():pytest.skip('Local game evidence is not distributed')
    image=cv2.imdecode(np.fromfile(path,np.uint8),cv2.IMREAD_COLOR)
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,real_ocr)
    assert vision.read_metric(image,'gold')==expected

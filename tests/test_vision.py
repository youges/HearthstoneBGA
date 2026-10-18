import json
import cv2
import numpy as np
import pytest

from bga.config import Profile
from bga.model import State,Token
from bga.vision import Vision,parse_number,classify_hand_text


class FakeOCR:
    def __init__(self,tokens=()):self.items=tokens
    def tokens(self,image):return list(self.items)


@pytest.mark.parametrize('description,label,expected',[
    ('获得1枚铸币。','酒馆','coin'),
    ('附魔链索，效果文字未完整读取','酒馆','steal'),
    ('随机偷取酒馆中的一个随从。','酒馆','steal'),
    ('使一个随从获得+3/+3。','酒馆','buff'),
    ('选择一个随从。在本局对战中，使酒馆中该类型的随从获得+3/+3。','酒馆','buff'),
    ('选择一个随从，使其失去所有生命并使酒馆该类型获得+3/+3。','酒馆','unknown'),
    ('发现一个亡语随从。','酒馆','discover'),
    ('消灭一个友方随从，获得3枚铸币。','酒馆','unknown'),
    ('使一个随从获得+3/+3。','机械','minion'),
    ('无法读取','','unknown'),
])
def test_hand_text_classification_requires_visible_type_label(description,label,expected):
    tokens=[Token(description,.99,(.4,.5,.2,.1)),Token(label,.99,(.45,.8,.1,.04))]
    assert classify_hand_text(tokens)==expected


@pytest.mark.parametrize('text,kind,expected',[
    ('第8名','placement',8),('9','placement',None),('8th','placement',8),
    ('第七名','placement',7),('第一名','placement',1),('第九名','placement',None),
    ('第四名！','placement',4),('第三名!','placement',3),('第4名!','placement',4),
    ('+100','rating',None),('-87','rating',None),('6,000','rating',6000),
    ('8/10','gold',8),('99','gold',None),('升级4','upgrade_cost',None),
])
def test_numeric_regions_do_not_confuse_delta_rank_or_cost(text,kind,expected):
    assert parse_number(text,kind)==expected


def template_fixture(tmp_path):
    rng=np.random.default_rng(42)
    image=np.zeros((450,800,3),dtype=np.uint8)+20
    patch=rng.integers(0,255,(35,80,3),dtype=np.uint8)
    image[90:125,240:320]=patch
    cv2.imencode('.png',patch)[1].tofile(tmp_path/'anchor.png')
    profile=Profile()
    profile.anchors={'hero':dict(file='anchor.png',box=[.3,.2,.1,35/450],frame_size=[800,450],threshold=.92)}
    return image,profile


def test_template_match_confirms_state_but_ocr_only_does_not(tmp_path):
    image,profile=template_fixture(tmp_path)
    obs=Vision(profile,tmp_path,FakeOCR()).analyze(image)
    assert obs.state==State.HERO and obs.trusted
    hint=Vision(Profile(),tmp_path,FakeOCR([Token('选择一个英雄',.99,(.2,.2,.3,.1))])).analyze(image)
    assert hint.state==State.HERO and not hint.trusted


def test_template_supports_proportional_resize(tmp_path):
    image,profile=template_fixture(tmp_path)
    larger=cv2.resize(image,(1600,900))
    obs=Vision(profile,tmp_path,FakeOCR()).analyze(larger)
    assert obs.state==State.HERO and obs.trusted


def test_wrong_aspect_does_not_authorize_old_coordinates(tmp_path):
    image,profile=template_fixture(tmp_path)
    obs=Vision(profile,tmp_path,FakeOCR()).analyze(cv2.resize(image,(800,600)))
    assert obs.state==State.UNKNOWN and not obs.trusted


def test_unverified_point_defaults_never_authorize_targets(tmp_path):
    image,profile=template_fixture(tmp_path)
    obs=Vision(profile,tmp_path,FakeOCR()).analyze(image)
    assert obs.targets=={}


def test_profile_rejects_out_of_bounds_region(tmp_path):
    file=tmp_path/'profile.json'
    file.write_text(json.dumps({'regions':{'gold':[.9,.9,.3,.3]}}),encoding='utf-8')
    with pytest.raises(ValueError,match='越界'):Profile.load(file)


def test_template_path_cannot_escape_project(tmp_path):
    vision=Vision(Profile(),tmp_path,FakeOCR())
    with pytest.raises(ValueError,match='项目目录'):vision.template({'file':'../foreign.png'})


def test_constant_color_template_is_rejected(tmp_path):
    cv2.imencode('.png',np.zeros((30,30,3),np.uint8))[1].tofile(tmp_path/'flat.png')
    with pytest.raises(ValueError,match='纯色'):Vision(Profile(),tmp_path,FakeOCR()).template({'file':'flat.png'})


def test_direct_main_route_does_not_require_nonexistent_modes_screen():
    profile=Profile(main_direct_battlegrounds=True)
    missing=profile.missing()
    assert '状态模板 modes' not in missing
    assert '坐标 mode_battlegrounds' not in missing
    assert '状态模板 hero' in missing
    assert '标记模板 minion' in missing


def test_notice_template_requires_close_point():
    profile=Profile(anchors={'notice':{'file':'notice.png'}})
    assert '坐标 notice_close' in profile.missing()


def test_combat_banner_suppresses_a_still_visible_recruit_anchor(tmp_path):
    image,profile=template_fixture(tmp_path)
    profile.anchors={'recruit':profile.anchors['hero']}
    token=Token('开始战斗',.99,(.76,.43,.08,.04))
    obs=Vision(profile,tmp_path,FakeOCR([token])).analyze(image)
    assert obs.state==State.COMBAT
    assert not obs.trusted  # no mouse action may be authorized by this cue

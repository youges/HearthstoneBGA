from pathlib import Path
import cv2
import numpy as np
import pytest
from bga.adaptation import fit_client,needs_fit
from bga.discovery import detect_battle_net
from bga.config import Profile
from bga.vision import Vision
from bga.model import State
from bga.model import Token

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('work',[(0,0,1366,728),(0,0,1920,1040),(0,0,2560,1400),
                                      (0,0,3840,2120),(0,0,1024,728),(-2560,0,0,1400),
                                      (0,0,3440,1400),(0,0,1080,1880)])
def test_fit_matches_calibration_inside_monitor_work_area(work):
    x,y,w,h=fit_client(work,(16,39),16/9)
    assert x>=work[0] and y>=work[1] and x+w<=work[2] and y+h<=work[3]
    cw,ch=w-16,h-39
    assert cw>=960 and ch>=540 and abs(cw/ch/(16/9)-1)<.01
    assert not needs_fit((x+8,y+31,cw,ch),(x,y,x+w,y+h),work,16/9)


def test_small_monitor_fails_without_producing_a_click_plan():
    with pytest.raises(ValueError,match='空间不足'):fit_client((0,0,800,600),(16,39),16/9)
    assert needs_fit((0,0,1280,800),(0,0,1296,839),(0,0,1920,1040),16/9)


def test_path_discovery_priority_stale_config_and_registry_directory(tmp_path):
    saved=tmp_path/'Battle.net Launcher.exe';saved.write_bytes(b'test fixture')
    running=tmp_path/'Battle.net.exe';running.write_bytes(b'test fixture')
    assert detect_battle_net(str(saved),[running],[],[])[1]=='已保存的路径'
    assert detect_battle_net('Z:/missing/Battle.net.exe',[running],[],[])[0]==str(running)
    assert detect_battle_net('',[],[tmp_path],[])[0]==str(saved)
    assert detect_battle_net('',[],[],[tmp_path])[1]=='常见安装目录'
    assert not detect_battle_net('',[],[],[])[0]


class NoOCR:
    def tokens(self,_):return []
    def recognize_line(self,_):return []


@pytest.mark.parametrize('size',[(1280,720),(1360,765),(1920,1080),(2560,1440),(3840,2160)])
@pytest.mark.parametrize('name,state',[('hero',State.HERO),('hero-selected',State.HERO),
                                    ('program-two-choice',State.CHOICE),('program-result-native',State.RESULT)])
def test_real_frame_state_and_normalized_targets_across_resolutions(size,name,state):
    path=ROOT/'data/calibration'/f'{name}.png'
    if not path.exists():pytest.skip('local real frame not included')
    image=cv2.imdecode(np.fromfile(path,np.uint8),1)
    obs=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,NoOCR()).analyze(cv2.resize(image,size))
    assert obs.state==state and obs.trusted
    if state==State.HERO:assert obs.available_heroes==[2,3]
    if name=='hero-selected':assert obs.metrics['hero_selected_slot']==2
    assert all(0<x<1 and 0<y<1 for x,y in obs.targets.values())


def test_launcher_uses_button_text_only_with_correct_game_and_clear_play_label(tmp_path):
    profile=Profile(layout_mode='pc_v1',verified_points=['launcher_play'])
    class OCR:
        def __init__(self,items):self.items=items
        def tokens(self,_):return self.items
    game=Token('炉石传说',.99,(.1,.15,.2,.1))
    button=Token('进入游戏',.99,(.1,.8,.1,.05))
    image=np.zeros((800,1280,3),np.uint8)
    obs=Vision(profile,tmp_path,OCR([game,button])).analyze(image,'launcher')
    assert obs.trusted and obs.state==State.LAUNCHER and obs.targets['launcher_play']==button.center
    for items in [[button],[game,Token('更新',.99,button.box)],[game,Token('进入游戏',.7,button.box)]]:
        assert not Vision(profile,tmp_path,OCR(items)).analyze(image,'launcher').trusted

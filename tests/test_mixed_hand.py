"""A changing spell-outline count must not invalidate a visually unchanged minion."""
from pathlib import Path
import json

import cv2
import numpy as np
import pytest

from bga.config import Profile
from bga.model import Observation,State,hand_marks_match
from bga.pc_layout import hand_card_mark
from bga.vision import Vision
from conftest import settle

ROOT=Path(__file__).resolve().parents[1]


def hand(targets,count=2,board=0):
    names=['banana','minion','banana_2','banana_3','banana_4'][:count]
    positions={'banana':(.40,.93),'minion':(.47,.93),'banana_2':(.54,.93),
               'banana_3':(.60,.93),'banana_4':(.66,.93)}
    marks={name:tuple([30+i*40]*144) for i,name in enumerate(names)}
    return Observation(State.RECRUIT,.99,True,dict(targets,**positions),
                       metrics={'gold':0,'hand_count':count},board_count=board,hand_minions=names,
                       hand_marks=marks,hand_priority=['minion'] if 'minion' in names else [])


def inspect_minion(engine,clock,obs):
    settle(engine,clock,obs)
    hover=engine.decide(obs)
    assert hover.target=='minion'
    engine.sent(hover,obs)
    tooltip=hand(obs.targets,len(obs.hand_minions))
    tooltip.metrics['hand_card_kind']='minion'
    settle(engine,clock,tooltip)
    clear=engine.decide(tooltip)
    assert clear.target=='clear_tooltip'
    engine.sent(clear,tooltip)


def test_changed_candidate_count_keeps_same_card_and_waits_for_two_fresh_frames(world,targets):
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    before=hand(targets,2)
    inspect_minion(engine,clock,before)
    after=hand(targets,4)
    settle(engine,clock,after,1)
    assert engine.decide(after) is None
    settle(engine,clock,after,1)
    use=engine.decide(after)
    assert use.target=='inspected_hand' and use.destination=='board_drop'
    assert after.targets['inspected_hand']==after.targets['minion']
    assert after.metrics['precast_hand_count']==4 and after.metrics['precast_board_count']==0


def test_changed_artwork_at_same_point_never_uses_the_old_minion_type(world,targets):
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    before=hand(targets,2);inspect_minion(engine,clock,before)
    changed=hand(targets,2)
    changed.hand_marks['minion']=tuple([220]*144)
    settle(engine,clock,changed)
    assert engine.decide(changed) is None
    clock.advance(7)
    action=engine.decide(changed)
    assert action is None or action.kind=='hover'
    assert engine.hand_probe is None


def test_candidate_outside_original_card_cannot_reuse_its_inspection(world,targets):
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    before=hand(targets,2);inspect_minion(engine,clock,before)
    changed=hand(targets,2);changed.targets['minion']=(.57,.93)
    settle(engine,clock,changed);clock.advance(7)
    action=engine.decide(changed)
    assert action is None or action.kind=='hover'


def test_board_growth_confirms_minion_even_when_raw_hand_count_is_unchanged(world,targets):
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    before=hand(targets,2);inspect_minion(engine,clock,before)
    normal=hand(targets,3);settle(engine,clock,normal)
    use=engine.decide(normal);engine.sent(use,normal)
    engine.hand_skipped.add(normal.targets['banana'])
    after=hand(targets,3,board=1)
    assert engine.feedback(use,normal,after)
    settle(engine,clock,after)
    next_action=engine.decide(after)
    assert engine.pending_hand_play is None and engine.probes_this_turn==0
    assert next_action is not None and next_action.kind=='hover'


def test_candidate_count_drop_with_same_card_still_present_is_not_cast_feedback(world,targets):
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    before=hand(targets,4);inspect_minion(engine,clock,before)
    settle(engine,clock,before)
    use=engine.decide(before);engine.sent(use,before)
    after=hand(targets,2)
    settle(engine,clock,after)
    assert not engine.feedback(use,before,after)
    assert engine.decide(after) is None
    assert engine.pending_hand_play is not None


def test_distinct_verified_cards_can_be_inspected_without_spell_starvation(world,targets):
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    obs=hand(targets,5);settle(engine,clock,obs)
    seen=[]
    for _ in range(5):
        hover=engine.decide(obs)
        assert hover is not None and hover.kind=='hover'
        seen.append(hover.target);engine.sent(hover,obs)
        clock.advance(5)
        clear=engine.decide(obs);assert clear.target=='clear_tooltip'
        engine.sent(clear,obs);settle(engine,clock,obs)
    assert len(set(seen))==5 and seen[0]=='minion'
    assert engine.decide(obs) is None and engine.probes_this_turn==5


def test_visual_jitter_in_skipped_card_does_not_cause_repeated_inspection(world,targets):
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    obs=hand(targets,2);settle(engine,clock,obs)
    engine.hand_skipped.add((.471,.929))
    action=engine.decide(obs)
    assert action.target=='banana'


def test_tavern_flag_is_priority_not_a_minion_classification(world,targets):
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    obs=hand(targets,2);settle(engine,clock,obs)
    engine.sent(engine.decide(obs),obs)
    tooltip=hand(targets,2);tooltip.metrics['hand_card_kind']='buff'
    settle(engine,clock,tooltip);engine.sent(engine.decide(tooltip),tooltip)
    settle(engine,clock,obs)
    action=engine.decide(obs)
    assert action is None or action.kind=='hover'  # no friendly target on an empty board


def test_low_information_marks_and_different_card_art_do_not_match():
    assert not hand_marks_match(None,(1,2))
    assert not hand_marks_match((),())
    assert not hand_marks_match((0,)*144,(100,)*144)


def test_plain_color_cannot_supply_a_card_identity():
    frame=np.full((864,1536,3),(10,70,200),np.uint8)
    assert hand_card_mark(frame,(.5,.93)) is None


def test_packaged_mixed_hand_flow_uses_real_descriptors_and_decisions(tmp_path):
    from bga.hand_qa import verify_mixed_hand
    (tmp_path/'data').mkdir()
    result=verify_mixed_hand(tmp_path)
    assert result['passed'] and result['two_fresh_frames_required']


class NoOCR:
    def tokens(self,_):return []
    def recognize_line(self,_):return []


def incident(index):
    qa=ROOT/'data/qa-20261025-mixed-hand'
    manifest=qa/'frames.json'
    if not manifest.exists():pytest.skip('Private mixed-hand screenshot is not distributed')
    events=json.loads(manifest.read_text(encoding='utf-8'))
    return cv2.imdecode(np.fromfile(qa/Path(events[index]['evidence_path']).name,np.uint8),1)


@pytest.mark.parametrize('width',[1280,1536,1920,2560])
@pytest.mark.parametrize('before,after,x',[(6,8,.4733),(13,15,.5352)])
def test_actual_minion_identity_survives_mixed_spell_outline_count_changes(width,before,after,x):
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,NoOCR())
    frames=[vision.analyze(cv2.resize(incident(i),(width,width*9//16),interpolation=cv2.INTER_AREA)) for i in (before,after)]
    a,b=frames
    first=min(a.hand_priority,key=lambda n:abs(a.targets[n][0]-x))
    second=min(b.hand_priority,key=lambda n:abs(b.targets[n][0]-x))
    assert abs(a.targets[first][0]-x)<.01 and abs(b.targets[second][0]-x)<.01
    assert hand_marks_match(a.hand_marks[first],b.hand_marks[second])
    wrong=[n for n in b.hand_minions if abs(b.targets[n][0]-x)>.04]
    assert all(not hand_marks_match(a.hand_marks[first],b.hand_marks[n]) for n in wrong)


@pytest.mark.parametrize('before,tooltip,after',[(6,7,8),(13,14,15)])
def test_actual_hovered_minion_can_be_played_after_candidates_change(world,before,tooltip,after):
    initial=incident(before)
    from bga.vision import Ocr
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,Ocr())
    engine,_,clock=world;engine.config.inspect_hand_cards=True
    obs=vision.analyze(initial);settle(engine,clock,obs)
    hover=engine.decide(obs);assert hover.target in obs.hand_priority
    engine.sent(hover,obs);vision.inspect_point=obs.targets[hover.target]
    inspected=vision.analyze(incident(tooltip));settle(engine,clock,inspected)
    assert inspected.metrics['hand_card_kind']=='minion'
    clear=engine.decide(inspected);assert clear.target=='clear_tooltip'
    engine.sent(clear,inspected);vision.inspect_point=None
    normal=vision.analyze(incident(after));settle(engine,clock,normal)
    assert normal.metrics['hand_count']!=obs.metrics['hand_count']
    use=engine.decide(normal)
    assert use.target=='inspected_hand' and use.destination=='board_drop'
    assert normal.metrics['precast_hand_kind']=='minion'

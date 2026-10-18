from pathlib import Path
import cv2
import pytest
from bga.pc_layout import board_count,count_tavern_stars,highlighted_friendly_target,targeting_arrow
from bga.config import Profile
from bga.vision import Vision
from bga.model import State

ROOT=Path(__file__).resolve().parents[1]


def frame(name):
    path=ROOT/'data/calibration'/f'{name}.png'
    if not path.exists():pytest.skip('本机校准素材未附带')
    return cv2.imread(str(path))


def test_background_detector_rejects_play_animation_and_tooltip():
    empty=frame('second-before-buy')
    assert board_count(frame('recruit-empty'),empty)==0
    assert board_count(frame('recruit-after-upgrade'),empty)==1
    assert board_count(frame('second-played'),empty) is None
    assert board_count(frame('recruit-before-upgrade'),empty) is None
    if (ROOT/'data/calibration/program-recruit-two.png').exists():
        native=cv2.resize(frame('program-recruit-two'),(1536,864),interpolation=cv2.INTER_AREA)
        assert board_count(native,empty)==2
    for name,n in [('program-recruit-three',3),('program-recruit-four',4)]:
        if (ROOT/f'data/calibration/{name}.png').exists():
            native=cv2.resize(frame(name),(1536,864),interpolation=cv2.INTER_AREA)
            assert board_count(native,empty)==n


@pytest.mark.parametrize('name',['20261017-board-four-golden','20261017-board-unknown-recruit'])
def test_shielded_golden_minion_still_counts_when_row_geometry_is_clear(name):
    image=cv2.resize(frame(name),(1536,864),interpolation=cv2.INTER_AREA)
    empty=cv2.resize(cv2.imread(str(ROOT/'assets/templates/live/empty-board-frame.png')),(1536,864))
    assert board_count(image,empty)==4


class NoOCR:
    def tokens(self,_):return []
    def recognize_line(self,_):return []


def test_real_two_choice_overlay_overrides_tavern_header():
    profile=Profile.load(ROOT/'profiles/pc-integration.json')
    vision=Vision(profile,ROOT,NoOCR())
    obs=vision.analyze(frame('program-two-choice'))
    assert obs.state==State.CHOICE and obs.trusted
    assert obs.targets['choice_1']==obs.targets['hero_2']
    image=cv2.resize(frame('program-two-choice'),(1536,864))
    assert count_tavern_stars(image)==4


def test_hero_fast_path_needs_no_ocr_and_still_checks_available_slots():
    class ForbiddenOCR:
        def tokens(self,_):raise AssertionError('hero path must not run OCR')
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,ForbiddenOCR())
    obs=vision.analyze(frame('hero'))
    assert obs.state==State.HERO and obs.trusted
    assert obs.available_heroes==[2,3]
    selected=vision.analyze(frame('hero-selected'))
    assert selected.metrics['hero_selected_slot']==2


def test_chained_unplayable_hand_card_is_not_dragged():
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,NoOCR())
    obs=vision.analyze(frame('program-locked-hand'))
    assert obs.state==State.RECRUIT and obs.trusted
    assert obs.hand_minions==[]


def test_three_card_discover_uses_its_own_card_center():
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,NoOCR())
    obs=vision.analyze(frame('program-discover-three'))
    assert obs.state==State.CHOICE and obs.trusted
    assert obs.targets['choice_1']==(.5,.43)


def test_three_card_choice_with_in_progress_title():
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,NoOCR())
    obs=vision.analyze(frame('choice-in-progress'))
    assert obs.state==State.CHOICE and obs.trusted
    assert obs.targets['choice_1']==(.5,.43)
    for name in ('recruit-empty','program-recruit-three','hero'):
        assert vision.analyze(frame(name)).state!=State.CHOICE


def test_two_minion_choice_does_not_click_the_gap_beneath_same_title():
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,NoOCR())
    obs=vision.analyze(frame('20261017-two-minion-choice'))
    assert obs.state==State.CHOICE and obs.trusted
    assert obs.targets['choice_1']==obs.targets['hero_2']


def test_opponent_connection_failure_overrides_lobby_before_retry():
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,NoOCR())
    obs=vision.analyze(frame('20261017-opponent-connection-error'))
    assert obs.state==State.DISCONNECT and obs.trusted
    assert obs.targets['reconnect']==(.498,.602)
    for name in ('recruit-empty','hero','second-before-buy'):
        assert vision.analyze(frame(name)).state!=State.DISCONNECT


@pytest.mark.parametrize('name',['weekly-quests-popup','daily-quests-popup'])
def test_quests_popup_is_a_notice_not_a_new_match(name):
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,NoOCR())
    obs=vision.analyze(frame(name))
    assert obs.state==State.NOTICE and obs.trusted
    assert 'notice_close' in obs.targets


def test_enlarged_minion_footer_recovers_full_frame_ocr_error():
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT)
    vision.inspect_point=(.4733072916666667,.9305555555555556)
    vision.inspect_source='hand'
    obs=vision.analyze(frame('program-generic-minion-tooltip'))
    assert obs.metrics['hand_card_kind']=='minion'
    assert obs.metrics['hand_type_from_footer']==1


def test_real_tier_six_has_six_verified_stars():
    image=cv2.resize(frame('program-tier6'),(1536,864),interpolation=cv2.INTER_AREA)
    assert count_tavern_stars(image)==6


@pytest.mark.parametrize('name,slot', [('20261017-footer-played',3),('20261017-discount-current',6)])
def test_real_discounted_shop_spell_keeps_green_price(name,slot):
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT)
    vision.inspect_shop_spells=True
    obs=vision.analyze(frame(name))
    assert f'spell_shop_{slot}' in obs.shop_spells
    assert obs.metrics[f'spell_shop_{slot}_cost']==1
    assert f'shop_{slot}' not in obs.shop_minions


def test_gold_minion_art_is_not_a_shop_spell_price():
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT)
    vision.inspect_shop_spells=True
    obs=vision.analyze(frame('20261017-shop-false-price'))
    assert obs.shop_minions==['shop_2','shop_3']
    assert obs.shop_spells==['spell_shop_4']
    assert obs.metrics['spell_shop_4_cost']==0


def test_generated_spells_without_tavern_flags_are_hover_candidates():
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,NoOCR())
    obs=vision.analyze(frame('20261017-shop-false-price'))
    assert len(obs.hand_minions)==2
    assert [obs.targets[n][0] for n in obs.hand_minions]==pytest.approx([.4525,.5215],abs=.005)


def test_real_random_tavern_theft_tooltip_is_a_nontargeted_spell():
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT)
    vision.inspect_point=(.4733072916666667,.9293981481481481)
    vision.inspect_source='hand'
    obs=vision.analyze(frame('20261017-random-steal-tooltip'))
    assert obs.metrics['hand_card_kind']=='steal'


def test_real_tier_five_uses_three_rows_of_stars():
    image=cv2.resize(frame('program-tier5'),(1536,864))
    assert count_tavern_stars(image)==5


def test_real_targeting_arrow_does_not_hide_verified_friendly_outline():
    image=cv2.resize(frame('program-targeting-positive'),(1536,864),interpolation=cv2.INTER_AREA)
    assert targeting_arrow(image)
    target=highlighted_friendly_target(image)
    assert target and abs(target[0]-.5)<.01
    assert .54<target[1]<.57


def test_known_full_board_target_stays_at_slot_center_instead_of_ring_peak():
    vision=Vision(Profile.load(ROOT/'profiles/pc-integration.json'),ROOT,NoOCR())
    obs=vision.analyze(frame('20261017-targeted-choice-arrow'))
    assert obs.state==State.RECRUIT and obs.board_count==7
    assert obs.targets['friendly_target']==pytest.approx((432/1536,470/864))


def test_real_hero_choices_require_available_plate_and_selected_border():
    profile=ROOT/'profiles/pc-integration.json'
    if not profile.exists():pytest.skip('本机 PC 布局不存在')
    vision=Vision(Profile.load(profile),ROOT,NoOCR())
    unselected=vision.analyze(frame('hero'))
    assert unselected.available_heroes==[2,3]
    assert 'hero_selected_slot' not in unselected.metrics
    selected=vision.analyze(frame('hero-selected'))
    assert selected.metrics['hero_selected_slot']==2
    shop=vision.analyze(frame('second-before-buy'))
    assert shop.shop_minions==['shop_1','shop_2','shop_3']
    assert 'shop_4' not in shop.shop_minions
    assert vision.analyze(frame('menu')).state==State.MENU
    assert vision.analyze(frame('confirm')).state==State.CONFIRM

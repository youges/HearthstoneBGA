"""A one-pixel result label variation must not stop an unlimited session."""
from pathlib import Path
import json

import cv2
import numpy as np
import pytest

from bga.config import Profile
from bga.model import Observation, State, Token
from bga.vision import Vision
from conftest import settle


ROOT = Path(__file__).resolve().parents[1]


class NoOCR:
    def tokens(self, image):
        return []

    def recognize_line(self, image):
        return []


def rendered_result(tmp_path, dx=0, dy=0, state='result'):
    # Deliberately nonuniform so a changed pixel size cannot pass by color alone.
    patch = np.random.default_rng(913).integers(0, 255, (36, 95, 3), dtype=np.uint8)
    cv2.imencode('.png', patch)[1].tofile(tmp_path / 'label.png')
    frame = np.full((540, 960, 3), 20, np.uint8)
    rendered = cv2.resize(patch, (95 + dx, 36 + dy), interpolation=cv2.INTER_CUBIC)
    frame[350:350 + rendered.shape[0], 435:435 + rendered.shape[1]] = rendered
    profile = Profile(anchors={state: {
        'file': 'label.png', 'box': [435 / 960, 350 / 540, 95 / 960, 36 / 540],
        'frame_size': [960, 540], 'threshold': .91,
    }})
    return frame, profile


@pytest.mark.parametrize('dx,dy', [(1, 1), (1, -1), (-1, 1), (-1, -1)])
def test_native_result_rounding_keeps_visual_confirmation(tmp_path, dx, dy):
    frame, profile = rendered_result(tmp_path, dx, dy)
    vision = Vision(profile, tmp_path, NoOCR())
    spec = profile.anchors['result']
    assert vision.match(frame, spec) < spec['threshold']
    result = vision.analyze(frame)
    assert result.state == State.RESULT and result.trusted
    assert result.confidence >= spec['threshold']


def test_rounding_does_not_expand_search_region_or_lower_threshold(tmp_path):
    frame, profile = rendered_result(tmp_path, 1, 1)
    vision = Vision(profile, tmp_path, NoOCR())
    moved = np.full_like(frame, 20)
    moved[80:117, 100:196] = frame[350:387, 435:531]
    assert not vision.analyze(moved).trusted
    assert not vision.analyze(np.full_like(frame, 20)).trusted
    # The tolerance is result-specific; other input states retain their behavior.
    profile.anchors['recruit'] = profile.anchors.pop('result')
    assert not vision.analyze(frame).trusted


def test_rank_text_alone_still_cannot_authorize_result_input(tmp_path):
    frame, profile = rendered_result(tmp_path)
    class TextOnly(NoOCR):
        def tokens(self, image):
            return [Token('第六名', .99, (.45, .58, .1, .05))]
    result = Vision(profile, tmp_path, TextOnly()).analyze(np.full_like(frame, 20))
    assert result.state == State.RESULT and not result.trusted


@pytest.mark.parametrize('width', [1280, 1536, 1920, 2560])
def test_actual_seventh_match_result_is_visually_trusted(width):
    path = ROOT / 'data/calibration/20261021-result-subpixel.png'
    if not path.exists():
        pytest.skip('Private incident screenshot is not distributed')
    frame = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
    frame = cv2.resize(frame, (width, round(frame.shape[0] * width / frame.shape[1])), interpolation=cv2.INTER_AREA)
    result = Vision(Profile.load(ROOT / 'profiles/pc-integration.json'), ROOT, NoOCR()).analyze(frame)
    assert result.state == State.RESULT and result.trusted


def test_twelve_matches_continue_past_six_with_rounded_result(world, targets, tmp_path):
    engine, store, clock = world
    engine.config.max_matches = 0
    frame, profile = rendered_result(tmp_path, 1, 1)
    vision = Vision(profile, tmp_path, NoOCR())
    for index in range(12):
        lobby = Observation(State.LOBBY, .99, True, targets, metrics={'rating': 2000})
        settle(engine, clock, lobby, 5)
        start = engine.decide(lobby)
        assert start.target == 'lobby_play'
        engine.sent(start, lobby)
        hero = Observation(State.HERO, .99, True, targets, available_heroes=[2, 3])
        settle(engine, clock, hero)
        choose = engine.decide(hero)
        engine.sent(choose, hero)
        settle(engine, clock, Observation(State.COMBAT, .99, True, targets))
        result = vision.analyze(frame)
        assert result.trusted
        result.targets = targets
        result.metrics = {'placement': 6, 'rating': 2000}
        settle(engine, clock, result, 5)
        leave = engine.decide(result)
        assert leave.target == 'result_continue'
        engine.sent(leave, result)
        settle(engine, clock, lobby, 5)
        assert engine.completed == index + 1
        assert not engine.done
    assert len(store.recent()) == 12
    assert all(row['result_status'] == 'complete' for row in store.recent())


def test_replay_can_require_visual_trust(tmp_path, monkeypatch):
    import bga.replay as replay
    frame, profile = rendered_result(tmp_path)
    cv2.imencode('.png', frame)[1].tofile(tmp_path / 'frame.png')
    profile.save(tmp_path / 'profile.json')
    manifest = {'profile_path': 'profile.json', 'cases': [{
        'match_id': 'untrusted-result', 'image': 'frame.png',
        'state': 'result', 'metrics': {}, 'trusted': True,
    }]}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    class HintOnlyVision:
        def __init__(self, *args):
            pass
        def analyze(self, image):
            return Observation(State.RESULT, .6, False)
    monkeypatch.setattr(replay, 'Vision', HintOnlyVision)
    assert replay.run_replay('manifest.json', root=tmp_path) == 1
    report = json.loads((tmp_path / 'data/vision-replay-result.json').read_text(encoding='utf-8'))
    assert report['checks'][0]['trusted'] is False
    assert not report['passed']

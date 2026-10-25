from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import sys


def project_root() -> Path:
    if getattr(sys, 'frozen', False):
        # The portable onedir folder has its own mutable data and profiles.
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


@dataclass
class Config:
    battle_net_path: str = ''
    profile_path: str = 'profiles/default.json'
    observe_only: bool = True
    poll_seconds: float = 1.5
    action_seconds: float = 1.2
    stable_frames: int = 2
    state_timeout: float = 240.0
    max_matches: int = 0
    preferred_hero: int = 2
    upgrade_max_cost: int = 30
    min_gold_after_upgrade: int = 3
    max_actions_per_turn: int = 35
    test_concede: bool = False
    concede_after_seconds: float = 60.0
    auto_launch: bool = True
    focus_on_start: bool = False
    recover_focus: bool = False
    auto_adapt_resolution: bool = True
    inspect_hand_cards: bool = False
    test_shop_spells: bool = False
    auto_sell_for_space: bool = False
    auto_concede_on_error: bool = False
    max_consecutive_recoveries: int = 3
    integration_seconds: int = 0
    resume_match_id: str = ''

    def validate(self):
        if self.preferred_hero not in (2, 3):
            raise ValueError('英雄偏好只能为 2 或 3')
        if not 0.3 <= self.poll_seconds <= 30:
            raise ValueError('识别间隔应在 0.3–30 秒之间')
        if not 0.3 <= self.action_seconds <= 30:
            raise ValueError('动作间隔应在 0.3–30 秒之间')
        if not 2 <= self.stable_frames <= 10:
            raise ValueError('稳定帧数应在 2–10 之间')
        if self.state_timeout < 15 or self.max_matches < 0:
            raise ValueError('超时至少 15 秒，局数不能为负')
        if not 0 <= self.upgrade_max_cost <= 30 or not 0 <= self.min_gold_after_upgrade <= 30:
            raise ValueError('升级经济参数超出范围')
        if self.concede_after_seconds < 5:
            raise ValueError('测试退出时间至少 5 秒')
        if self.auto_sell_for_space and not self.inspect_hand_cards:
            raise ValueError('自动腾位需要开启读取手牌说明')
        if not isinstance(self.max_consecutive_recoveries,int) or isinstance(self.max_consecutive_recoveries,bool) or not 1<=self.max_consecutive_recoveries<=20:
            raise ValueError('连续异常认输上限应为 1–20 局')

    @classmethod
    def load(cls, path: Path):
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding='utf-8'))
        value = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        value.validate()
        return value

    def save(self, path: Path):
        self.validate()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)


# Points are suggestions only: profile validation prevents live input before calibration.
DEFAULT_POINTS = {
    'launcher_play': [0.13, 0.88], 'entry_continue': [0.5, 0.6],
    'main_modes': [0.5, 0.55], 'mode_battlegrounds': [0.5, 0.4],
    'lobby_play': [0.82, 0.86], 'hero_2': [0.41, 0.47], 'hero_3': [0.59, 0.47],
    'hero_confirm': [0.5, 0.83], 'upgrade': [0.29, 0.16],
    'hand_drop': [0.5, 0.92], 'board_drop': [0.5, 0.59],
    'result_continue': [0.5, 0.78], 'concede': [0.5, 0.45],
    'confirm_concede': [0.6, 0.55], 'reconnect': [0.5, 0.6],
    'choice_1': [0.32, 0.48],
    **{f'shop_{i+1}': [0.29+i*0.085, 0.32] for i in range(7)},
    **{f'hand_{i+1}': [0.31+i*0.045, 0.92] for i in range(10)},
}
DEFAULT_REGIONS = {
    'gold': [0.84, 0.84, 0.14, 0.14], 'upgrade_cost': [0.22, 0.10, 0.12, 0.15],
    'tavern_tier': [0.2, 0.05, 0.14, 0.1], 'placement': [0.3, 0.15, 0.4, 0.3],
    'rating_lobby': [0.55, 0.6, 0.24, 0.2],
    'rating_result': [0.55, 0.6, 0.24, 0.2],
    'hero_2_region': [0.32, 0.2, 0.17, 0.5], 'hero_3_region': [0.51, 0.2, 0.17, 0.5],
    **{f'shop_{i+1}_region': [0.25+i*0.085, 0.19, 0.08, 0.25] for i in range(7)},
    **{f'hand_{i+1}_region': [0.287+i*0.045, 0.82, 0.045, 0.17] for i in range(10)},
    **{f'board_{i+1}_region': [0.24+i*0.075, 0.47, 0.07, 0.21] for i in range(7)},
}


@dataclass
class Profile:
    name: str = 'PC 客户端 / 待校准'
    calibrated: bool = False
    main_direct_battlegrounds: bool = False
    layout_mode: str = 'manual'
    validated_detectors: list[str] = field(default_factory=list)
    aspect_ratio: float = 16/9
    points: dict = field(default_factory=lambda: dict(DEFAULT_POINTS))
    regions: dict = field(default_factory=lambda: dict(DEFAULT_REGIONS))
    anchors: dict = field(default_factory=dict)
    markers: dict = field(default_factory=dict)
    verified_points: list[str] = field(default_factory=list)
    verified_regions: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path):
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding='utf-8'))
        p = cls(**{k:v for k,v in data.items() if k in cls.__dataclass_fields__})
        for mapping, size in [(p.points, 2), (p.regions, 4)]:
            for key, coords in mapping.items():
                if len(coords) != size or any(not isinstance(x,(int,float)) or not 0 <= x <= 1 for x in coords):
                    raise ValueError(f'校准坐标非法：{key}')
                if size == 4 and (coords[2] <= 0 or coords[3] <= 0 or coords[0]+coords[2]>1.001 or coords[1]+coords[3]>1.001):
                    raise ValueError(f'校准区域越界：{key}')
        if not 0.7 <= p.aspect_ratio <= 4:
            raise ValueError('窗口宽高比非法')
        return p

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)

    def missing(self) -> list[str]:
        required_points = ['launcher_play','entry_continue','main_modes','mode_battlegrounds','lobby_play',
                           'hero_2','hero_3','hero_confirm','upgrade','hand_drop','board_drop','result_continue']
        if self.main_direct_battlegrounds:
            required_points.remove('mode_battlegrounds')
        if 'notice' in self.anchors:
            required_points.append('notice_close')
        missing = [f'坐标 {k}' for k in required_points if k not in self.verified_points]
        required_regions = ['gold','upgrade_cost','tavern_tier','placement','rating_lobby','rating_result','hero_2_region','hero_3_region']
        missing += [f'区域 {k}' for k in required_regions if k not in self.verified_regions]
        for state in ['launcher','entry','main','modes','lobby','queue','hero','recruit','combat','result']:
            if state == 'modes' and self.main_direct_battlegrounds:
                continue
            if state not in self.anchors:
                missing.append(f'状态模板 {state}')
        if self.layout_mode == 'pc_v1':
            for name in ['hero_colors','shop_flags_stats','hand_flags','board_background']:
                if name not in self.validated_detectors:
                    missing.append(f'动态识别 {name}')
            return missing
        for name in ['hero_available','hero_locked','hero_selected','minion','board_minion','board_empty']:
            if name not in self.markers:
                missing.append(f'标记模板 {name}')
        # All slots must be explicitly verified; unverified defaults never authorize shopping.
        for group, count in [('shop',7),('hand',10),('board',7)]:
            for i in range(1,count+1):
                region = f'{group}_{i}_region'
                if region not in self.verified_regions:
                    missing.append(f'区域 {region}')
                if group != 'board' and f'{group}_{i}' not in self.verified_points:
                    missing.append(f'坐标 {group}_{i}')
        return missing

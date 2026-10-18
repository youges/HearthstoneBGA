from dataclasses import dataclass, field
from enum import StrEnum
import time


class State(StrEnum):
    UNKNOWN = 'unknown'
    LAUNCHER = 'launcher'
    ENTRY = 'entry'
    MAIN = 'main'
    MODES = 'modes'
    LOBBY = 'lobby'
    QUEUE = 'queue'
    HERO = 'hero'
    RECRUIT = 'recruit'
    COMBAT = 'combat'
    CHOICE = 'choice'
    RESULT = 'result'
    MENU = 'menu'
    CONFIRM = 'confirm'
    DISCONNECT = 'disconnect'
    AUTH = 'auth'
    NOTICE = 'notice'


STATE_NAMES = dict(zip(State, [
    '未知画面', '战网游戏页', '游戏入口', '游戏主菜单', '模式选择',
    '战棋大厅', '正在匹配', '初始英雄', '招募阶段', '战斗阶段',
    '发现 / 选择', '对局结算', 'Esc 菜单', '认输确认', '断线重连', '账号认证', '游戏公告',
]))

Point = tuple[float, float]
Box = tuple[float, float, float, float]


@dataclass
class Token:
    text: str
    score: float
    box: Box

    @property
    def center(self) -> Point:
        x, y, w, h = self.box
        return x + w / 2, y + h / 2


@dataclass
class Observation:
    state: State
    confidence: float = 0.0
    trusted: bool = False
    targets: dict[str, Point] = field(default_factory=dict)
    metrics: dict[str, int | str | None] = field(default_factory=dict)
    available_heroes: list[int] = field(default_factory=list)
    shop_minions: list[str] = field(default_factory=list)
    shop_spells: list[str] = field(default_factory=list)
    hand_minions: list[str] = field(default_factory=list)
    board_count: int | None = None
    tokens: list[Token] = field(default_factory=list)
    evidence: str = ''
    captured_at: float = field(default_factory=time.monotonic)


@dataclass
class Action:
    kind: str
    label: str
    target: str = ''
    destination: str = ''
    key: str = ''
    source_state: State = State.UNKNOWN
    captured_at: float = 0.0


@dataclass
class Match:
    id: str
    started_at: str
    hero_slot: int | None = None
    end_reason: str = 'normal'
    placement: int | None = None
    rating_before: int | None = None
    rating_after: int | None = None
    ended_at: str | None = None
    result_status: str = 'in_progress'
    evidence_path: str | None = None

    @property
    def rating_delta(self):
        if self.rating_before is None or self.rating_after is None:
            return None
        return self.rating_after - self.rating_before

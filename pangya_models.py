from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class GameWindowRect:
    left: int
    top: int
    right: int
    bottom: int
    width: int
    height: int


@dataclass
class RoiRect:
    name: str
    base_x: int
    base_y: int
    base_w: int
    base_h: int


@dataclass
class AutoDetectedInput:
    distance: Optional[float] = None
    height: Optional[float] = None
    wind: Optional[float] = None
    degree: Optional[float] = None
    slope: Optional[float] = 0.0
    ground: float = 100.0
    spin: float = 0.0
    curve: float = 0.0


@dataclass
class ShotDisplayResult:
    shot: str
    ok: bool
    power_percent: float = 0.0
    shot_yards: float = 0.0
    board_cells: float = 0.0
    smart_cells: float = 0.0
    message: str = ""


@dataclass
class OverlayCalcState:
    auto_input: AutoDetectedInput = field(default_factory=AutoDetectedInput)
    shot_results: Dict[str, ShotDisplayResult] = field(default_factory=dict)
    last_error: str = ""
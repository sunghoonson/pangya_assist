"""
Acrisio smart_calculator.js Python port.

원본 smart_calculator.js의 핵심 계산 흐름을 Python으로 옮긴 파일입니다.
- 클럽/파워/샷 타입 상수
- 공 물리 시뮬레이션 QuadTree
- find_power
- calc_shot: JS calc()와 유사하게 desvio 보정 반복까지 수행

주의:
- 게임 클라이언트의 완전한 공식 보증이 아니라, 첨부된 smart_calculator.js 포팅입니다.
- 원본 JS의 Math.random() 기반 slope line_ball은 Python에서 기본 0.0으로 고정했습니다.
  slope를 실제로 쓸 때 원본과 100% 동일 비교가 필요하면 line_ball_random=True 또는 line_ball 값을 직접 넣으세요.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
import math
import random
from typing import Optional, Union, Dict, Any


DESVIO_SCALE_PANGYA_TO_YARD = 0.3125 / 1.5

YARDS_TO_PB = 0.2167
YARDS_TO_PBA = 0.8668
YARDS_TO_PBA_PLUS = 1.032


class TypeDistance(IntEnum):
    LESS_10 = 0
    LESS_15 = 1
    LESS_28 = 2
    LESS_58 = 3
    BIGGER_OR_EQUAL_58 = 4


class PowerShotFactory(IntEnum):
    NO_POWER_SHOT = 0
    ONE_POWER_SHOT = 1
    TWO_POWER_SHOT = 2
    ITEM_15_POWER_SHOT = 3


class ClubType(IntEnum):
    WOOD = 0
    IRON = 1
    PW = 2
    PT = 3


class ShotType(IntEnum):
    DUNK = 0
    TOMAHAWK = 1
    SPIKE = 2
    COBRA = 3


@dataclass
class Vector3D:
    x: float
    y: float
    z: float

    def clone(self) -> "Vector3D":
        return Vector3D(self.x, self.y, self.z)

    def length(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def normalize(self) -> "Vector3D":
        return self.divide_scalar(self.length())

    def multiply_scalar(self, value: float) -> "Vector3D":
        self.x *= value
        self.y *= value
        self.z *= value
        return self

    def divide_scalar(self, value: float) -> "Vector3D":
        if value != 0:
            scalar = 1.0 / value
            self.x *= scalar
            self.y *= scalar
            self.z *= scalar
        else:
            self.x = 0.0
            self.y = 0.0
            self.z = 0.0
        return self

    def add(self, other: "Vector3D") -> "Vector3D":
        self.x += other.x
        self.y += other.y
        self.z += other.z
        return self

    def sub(self, other: "Vector3D") -> "Vector3D":
        self.x -= other.x
        self.y -= other.y
        self.z -= other.z
        return self

    def cross(self, other: "Vector3D") -> "Vector3D":
        x, y, z = self.x, self.y, self.z
        self.x = y * other.z - z * other.y
        self.y = z * other.x - x * other.z
        self.z = x * other.y - y * other.x
        return self


def calcule_type_distance(distance: float) -> TypeDistance:
    if distance >= 58.0:
        return TypeDistance.BIGGER_OR_EQUAL_58
    if distance < 10.0:
        return TypeDistance.LESS_10
    if distance < 15.0:
        return TypeDistance.LESS_15
    if distance < 28.0:
        return TypeDistance.LESS_28
    if distance < 58.0:
        return TypeDistance.LESS_58
    return TypeDistance.BIGGER_OR_EQUAL_58


@dataclass
class Ball:
    position: Vector3D = field(default_factory=lambda: Vector3D(0.0, 0.0, 0.0))
    slope: Vector3D = field(default_factory=lambda: Vector3D(0.0, 1.0, 0.0))
    state_process: int = 0
    max_height: float = 0.0
    max_altura: float = 0.0
    num_max_height: int = -1
    count: int = 0
    velocity: Vector3D = field(default_factory=lambda: Vector3D(0.0, 0.0, 0.0))
    ball_28: float = 0.0
    ball_2C: float = 0.0
    ball_30: float = 0.0
    ball_3C: float = 0.0
    ball_40: float = 0.0
    curva: float = 0.0
    spin: float = 0.0
    rotation_curve: float = 0.0
    rotation_spin: float = 0.0
    ball_44: int = 0
    ball_48: int = 0
    ball_70: int = -1
    ball_90: int = 0
    ball_BC: int = 0
    ball_C4: float = 0.0
    ball_C8: float = 0.0
    mass: float = 0.045926999
    diametro: float = 0.14698039

    def copy_from(self, other: "Ball") -> None:
        self.position = other.position.clone()
        self.slope = other.slope.clone()
        self.velocity = other.velocity.clone()
        self.state_process = other.state_process
        self.max_height = other.max_height
        self.max_altura = other.max_altura
        self.spin = other.spin
        self.curva = other.curva
        self.count = other.count
        self.num_max_height = other.num_max_height
        self.ball_28 = other.ball_28
        self.ball_2C = other.ball_2C
        self.ball_30 = other.ball_30
        self.ball_3C = other.ball_3C
        self.ball_40 = other.ball_40
        self.ball_44 = other.ball_44
        self.ball_48 = other.ball_48
        self.ball_70 = other.ball_70
        self.ball_90 = other.ball_90
        self.ball_BC = other.ball_BC
        self.ball_C4 = other.ball_C4
        self.ball_C8 = other.ball_C8
        self.rotation_curve = other.rotation_curve
        self.rotation_spin = other.rotation_spin
        self.mass = other.mass
        self.diametro = other.diametro


@dataclass(frozen=True)
class ClubInfo:
    type: ClubType
    rotation_spin: float
    rotation_curve: float
    power_factor: float
    degree: float
    power_base: float


CLUB_INFO: Dict[str, ClubInfo] = {
    "_1W": ClubInfo(ClubType.WOOD, 0.55, 1.61, 236.0, 10.0, 230.0),
    "_2W": ClubInfo(ClubType.WOOD, 0.50, 1.41, 204.0, 13.0, 210.0),
    "_3W": ClubInfo(ClubType.WOOD, 0.45, 1.26, 176.0, 16.0, 190.0),
    "_2I": ClubInfo(ClubType.IRON, 0.45, 1.07, 161.0, 20.0, 180.0),
    "_3I": ClubInfo(ClubType.IRON, 0.45, 0.95, 149.0, 24.0, 170.0),
    "_4I": ClubInfo(ClubType.IRON, 0.45, 0.83, 139.0, 28.0, 160.0),
    "_5I": ClubInfo(ClubType.IRON, 0.45, 0.73, 131.0, 32.0, 150.0),
    "_6I": ClubInfo(ClubType.IRON, 0.41, 0.67, 124.0, 36.0, 140.0),
    "_7I": ClubInfo(ClubType.IRON, 0.36, 0.61, 118.0, 40.0, 130.0),
    "_8I": ClubInfo(ClubType.IRON, 0.30, 0.57, 114.0, 44.0, 120.0),
    "_9I": ClubInfo(ClubType.IRON, 0.25, 0.53, 110.0, 48.0, 110.0),
    "PW": ClubInfo(ClubType.PW, 0.18, 0.49, 107.0, 52.0, 100.0),
    "SW": ClubInfo(ClubType.PW, 0.17, 0.42, 93.0, 56.0, 80.0),
    "PT1": ClubInfo(ClubType.PT, 0.00, 0.00, 30.0, 0.00, 20.0),
    "PT2": ClubInfo(ClubType.PT, 0.00, 0.00, 21.0, 0.00, 10.0),
}


def get_power_shot_factory(ps: Union[int, PowerShotFactory]) -> float:
    ps = PowerShotFactory(ps)
    if ps == PowerShotFactory.ONE_POWER_SHOT:
        return 10.0
    if ps == PowerShotFactory.TWO_POWER_SHOT:
        return 20.0
    if ps == PowerShotFactory.ITEM_15_POWER_SHOT:
        return 15.0
    return 0.0


@dataclass
class ExtraPower:
    auxpart: float = 0.0
    mascot: float = 4.0
    card: float = 4.0
    ps_auxpart: float = 0.0
    ps_mascot: float = 0.0
    ps_card: float = 8.0

    def total(self, option: Union[int, PowerShotFactory]) -> float:
        pwr = self.auxpart + self.mascot + self.card
        if int(option) in (1, 2, 3):
            pwr += self.ps_auxpart + self.ps_mascot + self.ps_card
        return pwr


@dataclass
class PowerPlayer:
    pwr: float = 31.0
    options: ExtraPower = field(default_factory=ExtraPower)


@dataclass
class Club:
    type: ClubType = ClubType.WOOD
    type_distance: TypeDistance = TypeDistance.BIGGER_OR_EQUAL_58
    rotation_spin: float = 0.55
    rotation_curve: float = 1.61
    power_factor: float = 236.0
    degree: float = 10.0
    power_base: float = 230.0

    def init(self, club_info: ClubInfo) -> None:
        self.type = club_info.type
        self.rotation_spin = club_info.rotation_spin
        self.rotation_curve = club_info.rotation_curve
        self.power_factor = club_info.power_factor
        self.degree = club_info.degree
        self.power_base = club_info.power_base

    def get_dreg_rad(self) -> float:
        return self.degree * math.pi / 180.0

    def get_power(self, extra_power: ExtraPower, pwr_slot: float, ps: PowerShotFactory, spin: float) -> float:
        pwrjard = 0.0

        if self.type == ClubType.WOOD:
            pwrjard = extra_power.total(ps) + get_power_shot_factory(ps) + ((pwr_slot - 15.0) * 2.0)
            pwrjard *= 1.5
            pwrjard /= self.power_base
            pwrjard += 1.0
            pwrjard *= self.power_factor

        elif self.type == ClubType.IRON:
            pwrjard = ((get_power_shot_factory(ps) / self.power_base + 1.0) * self.power_factor) + (
                extra_power.total(ps) * self.power_factor * 1.3
            ) / self.power_base

        elif self.type == ClubType.PW:
            def get_power_by_degree(degree: float, spin_value: float) -> float:
                return 0.5 + ((0.5 * (degree + (spin_value * _00D19B98))) / (56.0 / 180.0 * math.pi))

            if self.type_distance in (TypeDistance.LESS_10, TypeDistance.LESS_15, TypeDistance.LESS_28):
                pwrjard = (get_power_by_degree(self.get_dreg_rad(), spin) * (52.0 + (28.0 if ps else 0.0))) + (
                    extra_power.total(ps) * self.power_factor
                ) / self.power_base
            elif self.type_distance == TypeDistance.LESS_58:
                pwrjard = (get_power_by_degree(self.get_dreg_rad(), spin) * (80.0 + (18.0 if ps else 0.0))) + (
                    extra_power.total(ps) * self.power_factor
                ) / self.power_base
            elif self.type_distance == TypeDistance.BIGGER_OR_EQUAL_58:
                pwrjard = ((get_power_shot_factory(ps) / self.power_base + 1.0) * self.power_factor) + (
                    extra_power.total(ps) * self.power_factor
                ) / self.power_base

        elif self.type == ClubType.PT:
            pwrjard = self.power_factor

        return pwrjard

    def get_power2(self, extra_power: ExtraPower, pwr_slot: float, ps: PowerShotFactory) -> float:
        pwrjard = (extra_power.auxpart + extra_power.mascot + extra_power.card) / 2.0 + (pwr_slot - 15.0)
        if ps:
            pwrjard += extra_power.ps_card / 2.0
        pwrjard /= 170.0
        return pwrjard + 1.5

    def get_range(self, extra_power: ExtraPower, pwr_slot: float, ps: PowerShotFactory) -> float:
        pwr_range = self.power_base + extra_power.total(ps) + get_power_shot_factory(ps)

        if self.type == ClubType.WOOD:
            pwr_range += ((pwr_slot - 15.0) * 2.0)

        if self.type == ClubType.PW:
            if self.type_distance in (TypeDistance.LESS_10, TypeDistance.LESS_15, TypeDistance.LESS_28):
                pwr_range = 30.0 + (30.0 if ps else 0.0) + extra_power.total(ps)
            elif self.type_distance == TypeDistance.LESS_58:
                pwr_range = 60.0 + (20.0 if ps else 0.0) + extra_power.total(ps)
            elif self.type_distance == TypeDistance.BIGGER_OR_EQUAL_58:
                pwr_range = self.power_base + extra_power.total(ps) + get_power_shot_factory(ps)

        return pwr_range


@dataclass
class Wind:
    wind: float = 0.0
    degree: float = 0.0

    def get_wind(self) -> Vector3D:
        return Vector3D(
            self.wind * math.sin(self.degree * math.pi / 180.0) * -1.0,
            0.0,
            self.wind * math.cos(self.degree * math.pi / 180.0),
        )


# Original constants
_00D3D008 = 0.00001
_00D046A8 = -1.0
_00D00190 = 0.75
_00D083A0 = 0.02
_00D66CF8 = 3.0
_00D3D028 = 0.00008
_00D1A888 = 12.566371
_00D3D210 = 25.132742
_00CFF040 = 0.1
_00D66CA0 = 0.5
_00D16928 = 0.002
_00D17908 = 0.349065847694874
_00D19B98 = 0.0698131695389748
_00D16758 = 0.01

SLOPE_BREAK_TO_CURVE_SLOPE = 0.00875
_00E42544_VECT_SLOPE = Vector3D(0.0, 0.0, 1.0)


@dataclass
class ShotOptions:
    distance: float
    percent_shot: float
    ground: float
    mira_rad: float
    slope_mira_rad: float
    spin: float
    curva: float
    position: Vector3D
    shot: ShotType
    ps: PowerShotFactory
    power: PowerPlayer
    line_ball: float = 0.0


class QuadTree:
    def __init__(self) -> None:
        self.ball = Ball()
        self.club = Club()
        self.wind = Wind()
        self.gravity_factor = 1.0
        self.gravity = 34.295295715332
        self._21D8_vect = Vector3D(0.0, 0.0, 0.0)
        self.ball_position_init = Vector3D(0.0, 0.0, 0.0)
        self.power_range_shot = 0.0
        self.shot = ShotType.DUNK
        self.power_factor_shot = 0.0
        self.percent_shot_sqrt = 0.0
        self.spike_init = -1
        self.spike_med = -1
        self.power_factor = 0.0
        self.cobra_init = -1

    def get_gravity(self) -> float:
        return self.gravity * self.gravity_factor

    def init_shot(self, ball: Ball, club: Club, wind: Wind, options: ShotOptions) -> None:
        self.ball = ball
        self.club = club
        self.wind = wind
        self.shot = options.shot
        self.spike_init = -1
        self.spike_med = -1
        self.cobra_init = -1

        self.ball.position = options.position.clone()
        self.ball_position_init = options.position.clone()
        self.club.type_distance = calcule_type_distance(options.distance)
        self.ball.max_height = self.ball.position.y
        self.ball.count = 0
        self.ball.num_max_height = -1

        pwr = self.club.get_power(options.power.options, options.power.pwr, options.ps, options.spin)
        self.power_range_shot = self.club.get_range(options.power.options, options.power.pwr, options.ps)
        self.power_factor = pwr
        pwr *= math.sqrt(options.percent_shot)

        if options.shot in (ShotType.TOMAHAWK, ShotType.SPIKE):
            pwr *= 1.3
        else:
            pwr *= 1.0

        pwr *= math.sqrt(options.ground * 0.01)

        self.power_factor_shot = pwr
        self.percent_shot_sqrt = math.sqrt(options.percent_shot)

        self.ball.curva = options.curva
        self.ball.spin = options.spin

        value1 = self.get_values_degree(options.mira_rad + (0.0 - (self.ball.curva * _00D17908)), 1)
        value2 = self.get_values_degree(
            self.club.get_dreg_rad()
            if self.club.type_distance == TypeDistance.BIGGER_OR_EQUAL_58
            else self.club.get_dreg_rad() + (self.ball.spin * _00D19B98),
            0,
        )

        self.ball.curva -= self.get_slope(options.mira_rad - options.slope_mira_rad, options.line_ball)
        pwr *= (abs(self.ball.curva) * 0.1) + 1.0

        vect_a = Vector3D(value2["neg_sin"], value2["neg_rad"], value2["cos2"])
        vect_a.multiply_scalar(pwr)

        v1 = Vector3D(value1["cos"], value1["rad"], value1["sin"])
        v2 = Vector3D(value1["_C"], value1["_10"], value1["_14"])
        v3 = Vector3D(value1["neg_sin"], value1["neg_rad"], value1["cos2"])
        v4 = Vector3D(value1["_24"], value1["_28"], value1["_2C"])

        self.ball.velocity.x = v2.x * vect_a.y + vect_a.x * v1.x + v3.x * vect_a.z + v4.x
        self.ball.velocity.y = v1.y * vect_a.x + v2.y * vect_a.y + v3.y * vect_a.z + v4.y
        self.ball.velocity.z = v1.z * vect_a.x + v2.z * vect_a.y + v3.z * vect_a.z + v4.z

        self.ball.rotation_curve = self.ball.curva * options.percent_shot
        self.ball.rotation_spin = (
            (self.club.get_power2(options.power.options, options.power.pwr, options.ps) * options.percent_shot) * options.percent_shot
            if self.club.type_distance == TypeDistance.BIGGER_OR_EQUAL_58
            else 0.0
        )
        self.ball.ball_48 = self.ball.ball_44

    def get_values_degree(self, degree: float, option: int = 0) -> Dict[str, float]:
        obj: Dict[str, float] = {}
        if option == 0:
            obj["cos"] = 1.0
            obj["rad"] = 0.0
            obj["sin"] = 0.0
            obj["_C"] = 0.0
            obj["_10"] = math.cos(degree)
            obj["_14"] = math.sin(degree) * -1.0
            obj["neg_sin"] = 0.0
            obj["neg_rad"] = math.sin(degree)
            obj["cos2"] = obj["_10"]
            obj["_24"] = 0.0
            obj["_28"] = 0.0
            obj["_2C"] = 0.0
        elif option == 1:
            obj["cos"] = math.cos(degree)
            obj["rad"] = 0.0
            obj["sin"] = math.sin(degree)
            obj["_C"] = 0.0
            obj["_10"] = 1.0
            obj["_14"] = 0.0
            obj["neg_sin"] = obj["sin"] * -1.0
            obj["neg_rad"] = 0.0
            obj["cos2"] = obj["cos"]
            obj["_24"] = 0.0
            obj["_28"] = 0.0
            obj["_2C"] = 0.0
        return obj

    def get_slope(self, mira: float, line_ball: float) -> float:
        def values_degree_to_matrix(value: Dict[str, float]) -> Dict[str, Vector3D]:
            return {
                "v1": Vector3D(value["cos"], value["rad"], value["sin"]),
                "v2": Vector3D(value["_C"], value["_10"], value["_14"]),
                "v3": Vector3D(value["neg_sin"], value["neg_rad"], value["cos2"]),
                "v4": Vector3D(value["_24"], value["_28"], value["_2C"]),
            }

        def apply_matrix(m1: Dict[str, Vector3D], m2: Dict[str, Vector3D]) -> Dict[str, Vector3D]:
            return {
                "v1": Vector3D(
                    m1["v1"].x * m2["v1"].x + m1["v1"].y * m2["v2"].x + m1["v1"].z * m2["v3"].x,
                    m1["v1"].x * m2["v1"].y + m1["v1"].y * m2["v2"].y + m1["v1"].z * m2["v3"].y,
                    m1["v1"].x * m2["v1"].z + m1["v1"].y * m2["v2"].z + m1["v1"].z * m2["v3"].z,
                ),
                "v2": Vector3D(
                    m1["v2"].x * m2["v1"].x + m1["v2"].y * m2["v2"].x + m1["v2"].z * m2["v3"].x,
                    m1["v2"].x * m2["v1"].y + m1["v2"].y * m2["v2"].y + m1["v2"].z * m2["v3"].y,
                    m1["v2"].x * m2["v1"].z + m1["v2"].y * m2["v2"].z + m1["v2"].z * m2["v3"].z,
                ),
                "v3": Vector3D(
                    m1["v3"].x * m2["v1"].x + m1["v3"].y * m2["v2"].x + m1["v3"].z * m2["v3"].x,
                    m1["v3"].x * m2["v1"].y + m1["v3"].y * m2["v2"].y + m1["v3"].z * m2["v3"].y,
                    m1["v3"].x * m2["v1"].z + m1["v3"].y * m2["v2"].z + m1["v3"].z * m2["v3"].z,
                ),
                "v4": Vector3D(
                    m1["v4"].x * m2["v1"].x + m1["v4"].y * m2["v2"].x + m1["v4"].z * m2["v3"].x + m2["v4"].x,
                    m1["v4"].x * m2["v1"].y + m1["v4"].y * m2["v2"].y + m1["v4"].z * m2["v3"].y + m2["v4"].y,
                    m1["v4"].x * m2["v1"].z + m1["v4"].y * m2["v2"].z + m1["v4"].z * m2["v3"].z + m2["v4"].z,
                ),
            }

        ball_slope_cross_const_vect = self.ball.slope.clone().cross(_00E42544_VECT_SLOPE)
        slope_matrix = {
            "v1": ball_slope_cross_const_vect.clone().normalize(),
            "v2": self.ball.slope.clone(),
            "v3": ball_slope_cross_const_vect.clone().cross(self.ball.slope).normalize(),
            "v4": Vector3D(0.0, 0.0, 0.0),
        }

        value1 = self.get_values_degree(mira * -1.0, 1)
        value2 = self.get_values_degree(line_ball * -2.0, 1)
        m1 = apply_matrix(values_degree_to_matrix(value2), slope_matrix)
        m2 = apply_matrix(m1, values_degree_to_matrix(value1))
        return m2["v2"].x * _00D66CA0

    def ball_process(self, steptime: float, final: Optional[float] = None) -> None:
        self.bounce_process(steptime, final)

        if self.shot == ShotType.COBRA and self.cobra_init < 0:
            if self.percent_shot_sqrt < math.sqrt(0.8):
                self.percent_shot_sqrt = math.sqrt(0.8)

            if self.ball.count == 0:
                self.ball.velocity.y = 0.0
                self.ball.velocity.normalize().multiply_scalar(self.power_factor_shot)

            diff = self.ball.position.clone().sub(self.ball_position_init).length()
            cobra_init_up = ((self.power_range_shot * self.percent_shot_sqrt) - 100.0) * 3.2

            if diff >= cobra_init_up:
                power_multiply = 0.0
                if self.club.type == ClubType.WOOD:
                    if self.club.power_base == 230.0:
                        power_multiply = 74.0
                    elif self.club.power_base == 210.0:
                        power_multiply = 76.0
                    elif self.club.power_base == 190.0:
                        power_multiply = 80.0

                self.cobra_init = self.ball.count
                self.ball.velocity.normalize().multiply_scalar(power_multiply).multiply_scalar(self.percent_shot_sqrt)
                self.ball.rotation_spin = 2.5
        else:
            if self.spike_init < 0 and self.cobra_init < 0 and self.club.type_distance == TypeDistance.BIGGER_OR_EQUAL_58:
                self.ball.rotation_spin -= ((_00D66CA0 - (self.ball.spin * _00CFF040)) * _00D083A0)
            elif (self.shot == ShotType.SPIKE and self.spike_init >= 0) or (self.shot == ShotType.COBRA and self.cobra_init >= 0):
                self.ball.rotation_spin -= _00D083A0

            if self.shot == ShotType.SPIKE and self.ball.count == 0:
                self.ball.velocity.y = 0.0
                self.ball.velocity.normalize().multiply_scalar(self.power_factor_shot)
                self.ball.velocity.normalize().multiply_scalar(72.5).multiply_scalar(self.percent_shot_sqrt * 2.0)
                self.ball.rotation_spin = 3.1
                self.spike_init = self.ball.count

            if self.shot == ShotType.SPIKE and self.ball.num_max_height >= 0 and (self.ball.num_max_height + 0x3C) < self.ball.count and self.spike_med < 0:
                self.spike_med = self.ball.count
                if self.club.type == ClubType.WOOD:
                    new_power = 0.0
                    if self.club.power_base == 230.0:
                        new_power = 344.0
                        if (self.power_factor * self.percent_shot_sqrt) < 344.0:
                            new_power -= (self.power_factor * self.percent_shot_sqrt)
                        else:
                            new_power = 0.0
                        new_power = new_power / 112.0 * 21.5
                        new_power = -8.0 - new_power
                        self.ball.velocity.y = new_power
                    elif self.club.power_base == 210.0:
                        new_power = 306.0
                        if (self.power_factor * self.percent_shot_sqrt) < 306.0:
                            new_power -= (self.power_factor * self.percent_shot_sqrt)
                        else:
                            new_power = 0.0
                        new_power = new_power / 105.0 * 20.5
                        new_power = -10.3 - new_power
                        self.ball.velocity.y = new_power
                    elif self.club.power_base == 190.0:
                        new_power = 273.0
                        if (self.power_factor * self.percent_shot_sqrt) < 273.0:
                            new_power -= (self.power_factor * self.percent_shot_sqrt)
                        else:
                            new_power = 0.0
                        new_power = new_power / 100.0 * 20.2
                        new_power = -10.8 - new_power
                        self.ball.velocity.y = new_power

                self.ball.velocity.multiply_scalar(self.percent_shot_sqrt * 7.0)
                self.ball.rotation_spin = self.ball.spin

        if self.ball.velocity.y < 0.0 and self.ball.num_max_height < 0:
            self.ball.max_altura = self.ball.position.y
            self.ball.num_max_height = self.ball.count

        self.ball.count += 1

    def bounce_process(self, steptime: float, final: Optional[float] = None) -> None:
        if self.shot == ShotType.SPIKE and self.ball.num_max_height >= 0 and (self.ball.num_max_height + 0x3C) > self.ball.count:
            return

        accell_vect = self.apply_force()
        other_vect = accell_vect.clone().divide_scalar(self.ball.mass).multiply_scalar(steptime)
        self.ball.velocity.add(other_vect)

        if self.ball.num_max_height == -1:
            tmp_vect = self._21D8_vect.clone().divide_scalar(self.ball.mass).multiply_scalar(steptime)
            self.ball.velocity.add(tmp_vect)

        self.ball.ball_2C += self.ball.rotation_curve * _00D1A888 * steptime
        self.ball.ball_30 += self.ball.rotation_spin * _00D3D210 * steptime
        self.ball.position.add(self.ball.velocity.clone().multiply_scalar(final if final is not None else steptime))

    def apply_force(self) -> Vector3D:
        ret_vect = Vector3D(0.0, 0.0, 0.0)

        if self.ball.rotation_curve != 0.0:
            vectorb = Vector3D(self.ball.velocity.z * _00D046A8, 0.0, self.ball.velocity.x)
            vectorb.normalize()
            # 원본 조건은 OR입니다. spike_init/cobra_init 초기 상태에서는 대부분 true입니다.
            if self.cobra_init < 0 or self.spike_init < 0:
                vectorb.multiply_scalar(_00D00190 * self.ball.rotation_curve * self.club.rotation_curve)
            ret_vect.add(vectorb)

        if self.shot == ShotType.SPIKE and self.spike_init < 0:
            return Vector3D(0.0, 0.0, 0.0)
        if self.shot == ShotType.COBRA and self.cobra_init < 0:
            return ret_vect

        wind_vect = self.wind.get_wind()
        wind_vect.multiply_scalar(_00D16758 if self.shot == ShotType.SPIKE else _00D083A0)
        ret_vect.add(wind_vect)

        ret_vect.y = ret_vect.y - (self.get_gravity() * self.ball.mass)

        if self.ball.rotation_spin != 0.0:
            ret_vect.y = ret_vect.y + (self.club.rotation_spin * _00D66CF8 * self.ball.rotation_spin)

        vel_vect = self.ball.velocity.clone()
        vel_vect.multiply_scalar(vel_vect.length() * _00D3D028)
        ret_vect.sub(vel_vect)
        return ret_vect


@dataclass
class SmartData:
    desvio: float
    altura: float
    club: Club
    options: ShotOptions


@dataclass
class FoundResult:
    power: float = -1.0
    desvio: float = 0.0
    power_range: float = 0.0
    smart_data: Optional[SmartData] = None
    final_ball: Optional[Ball] = None
    iterations: int = 0

    @property
    def ok(self) -> bool:
        return self.power != -1.0


def make_slope(value: Union[float, str, Vector3D]) -> Union[float, Vector3D]:
    if isinstance(value, Vector3D):
        return value
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return 0.0
        parts = [p.strip() for p in value.split(",")]
        if len(parts) == 3:
            return Vector3D(
                float(parts[0]) * SLOPE_BREAK_TO_CURVE_SLOPE,
                float(parts[1]) * math.pi / 180.0,
                float(parts[2]) * SLOPE_BREAK_TO_CURVE_SLOPE,
            )
        return float(value)
    return float(value)


def find_power(
    power_player: PowerPlayer,
    club_info: ClubInfo,
    shot: ShotType,
    power_shot: PowerShotFactory,
    distancia: float,
    altura: float,
    vento: float,
    angulo: float,
    terreno: float,
    spin: float,
    curva: float,
    slope: Union[float, Vector3D] = 0.0,
    mira: Optional[float] = None,
    percent: Optional[float] = None,
    *,
    line_ball: float = 0.0,
    line_ball_random: bool = False,
) -> FoundResult:
    altura_colision = altura * 1.094 * 3.2
    distancia_scale = distancia * 3.2
    vball = Ball()
    vclub = Club()
    vclub.init(club_info)
    vclub.type_distance = calcule_type_distance(distancia)

    slope_mira_rad = 0.0
    slope = make_slope(slope)

    if isinstance(slope, Vector3D):
        slope_mira_rad = slope.y
        vball.slope = slope.clone()
        vball.slope.y = 1.0
    else:
        vball.slope = Vector3D(float(slope) * SLOPE_BREAK_TO_CURVE_SLOPE * -1.0, 1.0, 0.0)

    margin = 0.05
    limit_checking = 1000
    count = 0
    is_find = False
    found = FoundResult()

    wind = Wind(vento, angulo)
    options = ShotOptions(
        distance=distancia,
        percent_shot=percent if percent is not None else 1.0,
        ground=terreno if terreno != 0.0 else 100.0,
        mira_rad=mira if mira is not None else 0.0,
        slope_mira_rad=slope_mira_rad,
        spin=spin / 30.0,
        curva=curva / 30.0,
        position=Vector3D(0.0, 0.0, 0.0),
        shot=shot,
        ps=power_shot,
        power=power_player,
        line_ball=random.random() if line_ball_random else line_ball,
    )

    power_range = vclub.get_range(options.power.options, options.power.pwr, options.ps)

    def find_altura_colision(qt: QuadTree, altura_target: float) -> float:
        nonlocal vball
        local_count = 0
        copy_ball = Ball()

        while True:
            copy_ball.copy_from(vball)
            qt.ball_process(_00D083A0)
            local_count += 1
            if not ((vball.position.y > altura_target or vball.num_max_height == -1) and local_count < 3000):
                break

        denom = vball.position.y - copy_ball.position.y
        last_step = 0.0 if denom == 0 else abs((altura_target - copy_ball.position.y) / denom)
        vball.copy_from(copy_ball)
        qt.ball_process(_00D083A0, _00D083A0 * last_step)

        if abs(distancia_scale - vball.position.z) <= margin:
            return 0.0
        return distancia_scale - vball.position.z

    qt = QuadTree()
    lado = 0
    feed = 0.00006
    ret = 0.0

    while not is_find and count < limit_checking:
        if options.percent_shot > 1.3:
            options.percent_shot = 1.3
        elif options.percent_shot < 0.0:
            options.percent_shot = 0.1

        qt.init_shot(vball, vclub, wind, options)
        ret = find_altura_colision(qt, altura_colision)

        if ret == 0.0:
            is_find = True
        else:
            if options.percent_shot == 1.3 and ret > 0.0:
                break
            if options.percent_shot == 0.1 and ret < 0.0:
                break

            if lado == 0:
                lado = -1 if ret < 0.0 else 1
            elif (ret < 0.0 and lado == 1) or (ret > 0.0 and lado == -1):
                feed *= 0.5

            options.percent_shot += ret * feed

        count += 1

    if is_find:
        found.power = options.percent_shot
        found.desvio = (vball.position.x + (options.position.x + (math.tan(options.mira_rad) * distancia_scale))) * DESVIO_SCALE_PANGYA_TO_YARD
        found.power_range = power_range
        found.smart_data = SmartData(found.desvio, altura_colision, vclub, options)
        found.final_ball = Ball()
        found.final_ball.copy_from(vball)
        found.iterations = count

    return found


def desvio_by_degree(yards: float, distance: float) -> float:
    return math.sin(math.atan2(yards * -1.5, distance)) * distance / 1.5


def get_resolution_pb_limit(width: float = 800.0, height: float = 600.0) -> float:
    value = ((480.0 / height * 0.006) * (width / 2.0)) / YARDS_TO_PB
    return value if value > 0 else 1.0


def smart_desvio(smart_data: SmartData, *, max_pb: float = 0.0, resolution_width: float = 800.0, resolution_height: float = 600.0) -> str:
    if max_pb <= 0.0:
        max_pb = math.floor(get_resolution_pb_limit(resolution_width, resolution_height) * 10.0) / 10.0

    yards = desvio_by_degree(smart_data.desvio, smart_data.options.distance)

    pb_sample = yards / YARDS_TO_PB
    if abs(pb_sample) <= max_pb:
        return f"{pb_sample:.2f}pb"

    pb_sample = yards / YARDS_TO_PBA
    if abs(pb_sample) <= max_pb:
        return f"{pb_sample:.2f}pba"

    pb_sample = yards / YARDS_TO_PBA_PLUS
    if abs(pb_sample) <= max_pb:
        return f"{pb_sample:.2f}pba+"

    power_range = 230.0
    temp_club = Club()
    for club_name in ["SW", "PW", "_9I", "_8I", "_7I", "_6I", "_5I", "_4I", "_3I", "_2I", "_3W", "_2W", "_1W"]:
        temp_club.init(CLUB_INFO[club_name])
        power_range = temp_club.get_range(smart_data.options.power.options, smart_data.options.power.pwr, smart_data.options.ps)
        denom = ((power_range * 3.2 * 1.4 - smart_data.altura) * 0.0625)
        if denom != 0:
            pb_sample = (yards / YARDS_TO_PB) / denom
        if abs(pb_sample) <= max_pb:
            return f"{pb_sample:.2f}pba{power_range:.0f}"

    return f"{pb_sample:.2f}pba{power_range:.0f}"


@dataclass
class CalcResult:
    ok: bool
    power_percent: float = -1.0
    shot_yards: float = -1.0
    desvio_yards: float = 0.0
    pb: float = 0.0
    real_pb: float = 0.0
    smart: str = ""
    raw: Optional[FoundResult] = None
    aim_iterations: int = 0
    message: str = ""


def calc_shot(
    *,
    power: float = 31.0,
    auxpart_pwr: float = 0.0,
    card_pwr: float = 4.0,
    mascot_pwr: float = 4.0,
    card_ps_pwr: float = 8.0,
    club: str = "_1W",
    shot: Union[str, ShotType] = "TOMAHAWK",
    power_shot: Union[str, PowerShotFactory] = "NO_POWER_SHOT",
    distance: float,
    height: float = 0.0,
    wind: float = 0.0,
    degree: float = 0.0,
    ground: float = 100.0,
    spin: float = 0.0,
    curve: float = 0.0,
    slope: Union[float, str, Vector3D] = 0.0,
    max_aim_iterations: int = 20,
    line_ball: float = 0.0,
    line_ball_random: bool = False,
) -> CalcResult:
    if club not in CLUB_INFO:
        raise ValueError(f"Unknown club: {club}. available={list(CLUB_INFO.keys())}")

    shot_type = shot if isinstance(shot, ShotType) else ShotType[str(shot).upper()]
    ps_type = power_shot if isinstance(power_shot, PowerShotFactory) else PowerShotFactory[str(power_shot).upper()]

    power_player = PowerPlayer(
        pwr=power,
        options=ExtraPower(
            auxpart=auxpart_pwr,
            mascot=mascot_pwr,
            card=card_pwr,
            ps_card=card_ps_pwr,
        ),
    )

    found = find_power(
        power_player,
        CLUB_INFO[club],
        shot_type,
        ps_type,
        distance,
        height,
        wind,
        degree,
        ground if ground != 0.0 else 100.0,
        spin,
        curve,
        slope,
        line_ball=line_ball,
        line_ball_random=line_ball_random,
    )

    results = [found]
    index = 0

    if found.ok:
        while index < max_aim_iterations:
            index += 1
            prev = results[index - 1]
            next_found = find_power(
                power_player,
                CLUB_INFO[club],
                shot_type,
                ps_type,
                distance,
                height,
                wind,
                degree,
                ground if ground != 0.0 else 100.0,
                spin,
                curve,
                slope,
                mira=math.atan2(prev.desvio * 1.5, distance),
                percent=prev.power,
                line_ball=line_ball,
                line_ball_random=line_ball_random,
            )
            results.append(next_found)
            if not next_found.ok or not prev.ok or abs(prev.desvio - next_found.desvio) < 0.05:
                break

    final = results[-1]
    if final.ok and final.smart_data is not None:
        pb = desvio_by_degree(final.desvio, distance) / YARDS_TO_PB
        real_pb = final.desvio / YARDS_TO_PB * -1.0
        return CalcResult(
            ok=True,
            power_percent=final.power * 100.0,
            shot_yards=final.power_range * final.power,
            desvio_yards=final.desvio,
            pb=pb,
            real_pb=real_pb,
            smart=smart_desvio(final.smart_data),
            raw=final,
            aim_iterations=index,
            message="ok",
        )

    return CalcResult(ok=False, raw=final, aim_iterations=index, message="계산 실패: 거리가 닿지 않거나 너무 약한 조건입니다.")


__all__ = [
    "Vector3D",
    "Ball",
    "ClubInfo",
    "Club",
    "Wind",
    "ExtraPower",
    "PowerPlayer",
    "ShotType",
    "PowerShotFactory",
    "CLUB_INFO",
    "find_power",
    "calc_shot",
    "desvio_by_degree",
    "smart_desvio",
    "CalcResult",
]

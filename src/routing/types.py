"""连线相关数据结构。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class PinState:
    """引脚状态（修改前/后）。"""
    name: str           # 引脚名，如 PI, P1
    ref: str            # 所属器件 Reference，如 C1
    x: float            # 绝对坐标 (um)
    y: float

    def displacement(self, other: PinState) -> Tuple[float, float]:
        """计算到另一个状态的位移向量。"""
        return (other.x - self.x, other.y - self.y)

    def distance(self, other: PinState) -> float:
        """计算到另一个状态的距离。"""
        return math.sqrt((other.x - self.x) ** 2 + (other.y - self.y) ** 2)

    @property
    def key(self) -> str:
        """唯一标识: ref.pin_name。"""
        return f"{self.ref}.{self.name}"


@dataclass
class WireSegment:
    """一段走线。"""
    layer: Tuple[int, int]                       # (layer, datatype)
    points: List[Tuple[float, float]]            # 走线路径点 (um)，≥2个
    width: float                                 # 线宽 (um)

    @property
    def is_straight(self) -> bool:
        return len(self.points) == 2

    @property
    def is_l_shape(self) -> bool:
        return len(self.points) == 3

    @property
    def is_horizontal(self) -> bool:
        """直线且水平。"""
        return self.is_straight and abs(self.points[0][1] - self.points[1][1]) < 0.01

    @property
    def is_vertical(self) -> bool:
        """直线且垂直。"""
        return self.is_straight and abs(self.points[0][0] - self.points[1][0]) < 0.01


@dataclass
class Connection:
    """一条连线（连接两个引脚）。"""
    net_name: str
    pin_a: PinState       # 引脚 A
    pin_b: PinState       # 引脚 B
    wires: List[WireSegment] = field(default_factory=list)


@dataclass
class StretchResult:
    """拉伸结果。"""
    stretched: List[str] = field(default_factory=list)   # 成功拉伸的网络名
    broken: List[str] = field(default_factory=list)      # 超阈值断线的网络名
    total: int = 0

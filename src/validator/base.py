"""验证模块抽象基类与数据结构。"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class Violation:
    """单条违例。"""
    rule_name: str          # 如 "metal1.min_spacing"
    severity: Severity
    layer: str              # 如 "Metal1"
    x: float                # 违例中心坐标x (um)
    y: float                # 违例中心坐标y (um)
    description: str        # 如 "间距 0.8um < 最小 1.0um"
    related_refs: Optional[List[str]] = None  # 关联的器件Reference


@dataclass
class ValidationResult:
    """验证结果。"""
    passed: bool
    violation_count: int
    violations: List[Violation] = field(default_factory=list)
    report_path: str = ""

    def has_errors(self) -> bool:
        return any(v.severity == Severity.ERROR for v in self.violations)

    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.ERROR)

    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == Severity.WARNING)

    def violations_by_ref(self) -> dict[str, List[Violation]]:
        """按关联器件分组。"""
        result: dict[str, List[Violation]] = {}
        for v in self.violations:
            refs = v.related_refs or ["__unknown__"]
            for ref in refs:
                result.setdefault(ref, []).append(v)
        return result


class BaseValidator(abc.ABC):
    """验证器抽象基类。"""

    @abc.abstractmethod
    def run(self, gds_path: str, rules_path: str) -> ValidationResult:
        """运行验证。

        Args:
            gds_path: 待验证的GDS文件路径
            rules_path: 验证规则文件路径

        Returns:
            ValidationResult
        """
        ...


# ─────────────────────────────────────────────────────────────────
# LVS 数据结构
# ─────────────────────────────────────────────────────────────────

@dataclass
class LVSViolation:
    """单个 LVS 违例。"""
    violation_type: str           # "OPEN" | "SHORT" | "MISMATCH"
    net_name: str                 # 违例对应的网名
    expected_pins: Set[str]       # KiCad网表期望的引脚集合
    actual_pins: Set[str]         # GDS实际连通到的引脚集合
    description: str               # 人类可读描述

    def __post_init__(self):
        self.violation_type = self.violation_type.upper()
        if self.violation_type not in ("OPEN", "SHORT", "MISMATCH"):
            raise ValueError(f"Invalid violation_type: {self.violation_type}")


@dataclass
class LVSResult:
    """LVS 验证结果。"""
    passed: bool
    violations: List[LVSViolation] = field(default_factory=list)
    physical_nets: Dict[int, Set[str]] = field(default_factory=dict)  # region_id → pin_names

    def add_open(self, net_name: str, expected: Set[str], actual: Set[str]):
        self.violations.append(LVSViolation(
            violation_type="OPEN",
            net_name=net_name,
            expected_pins=expected,
            actual_pins=actual,
            description=f"OPEN: Net '{net_name}' expected pins {expected}, got {actual}",
        ))
        self.passed = False

    def add_short(self, net_name: str, extra_pins: Set[str]):
        self.violations.append(LVSViolation(
            violation_type="SHORT",
            net_name=net_name,
            expected_pins=set(),
            actual_pins=extra_pins,
            description=f"SHORT: Net '{net_name}' has unexpected pins {extra_pins}",
        ))
        self.passed = False

    @property
    def open_count(self) -> int:
        return sum(1 for v in self.violations if v.violation_type == "OPEN")

    @property
    def short_count(self) -> int:
        return sum(1 for v in self.violations if v.violation_type == "SHORT")


class BaseLVSRunner(abc.ABC):
    """LVS 执行器抽象基类。"""

    @abc.abstractmethod
    def run(
        self,
        gds_path: str,
        schematic_nets: Dict[str, List[str]],           # {net_name: [ref.pin_name, ...]}
        pin_positions: Dict[str, Tuple[float, float]],  # {ref.pin_name: (x_um, y_um)}
    ) -> LVSResult:
        """执行 LVS 比对。

        Args:
            gds_path: GDS 文件路径
            schematic_nets: KiCad 解析得到的网表连接 {net: [pin, ...]}
            pin_positions: {ref.pin_name: (x, y)} 引脚全局坐标(um)

        Returns:
            LVSResult
        """
        ...

    def supports_device_check(self) -> bool:
        """是否支持器件参数精细比对。KLayoutPureLVS 不支持。"""
        return False

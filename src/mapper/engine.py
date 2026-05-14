"""带约束的映射引擎：电气值 → 几何参数，含边界过滤。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from parser.target_params import TargetParam


@dataclass
class MappedGeometry:
    """映射后的几何参数。"""
    reference: str            # 器件reference
    target_pcell: str         # 对应PCell名
    geometry_params: dict     # 几何参数，如 {"length": 57, "width": 57}
    warnings: list[str] = field(default_factory=list)


class MappingEngine:
    """带约束的映射引擎。

    首期：查表映射 + 静态边界过滤。
    二期预留：空间感知约束、多解选择。
    """

    def __init__(self, rules_path: str | Path):
        self._rules = self._load_rules(rules_path)

    def _load_rules(self, path: str | Path) -> dict:
        path = Path(path)
        content = path.read_text(encoding="utf-8")
        return yaml.safe_load(content)

    def map(self, target: TargetParam) -> MappedGeometry:
        """将目标电气参数映射为几何参数。"""
        rule = self._rules.get(target.device_type)
        if rule is None:
            raise ValueError(f"无映射规则: device_type={target.device_type}")

        target_pcell = rule["target_pcell"]
        constraints = rule.get("constraints", {})
        lookup_table = rule.get("lookup_table", [])
        param_mapping = rule.get("param_mapping", {})  # 查表结果字段名→PCell参数名
        defaults = rule.get("defaults", {})             # PCell参数默认值

        # 查表
        raw_geometry = self._lookup(target.params, lookup_table, param_mapping)
        if raw_geometry is None:
            raise ValueError(
                f"查表无匹配: device_type={target.device_type}, "
                f"params={target.params}"
            )

        # 字段名映射：如 length_um → length
        geometry = {}
        for k, v in raw_geometry.items():
            mapped_key = param_mapping.get(k, k)
            geometry[mapped_key] = v

        # 补充默认参数
        for k, v in defaults.items():
            if k not in geometry:
                geometry[k] = v

        # 约束过滤
        warnings = self._check_constraints(geometry, constraints)

        return MappedGeometry(
            reference=target.reference,
            target_pcell=target_pcell,
            geometry_params=geometry,
            warnings=warnings,
        )

    def _lookup(self, params: dict, table: list[dict], param_mapping: dict) -> Optional[dict]:
        """查表找最近匹配。比较电气参数列，选距离最小的行。

        param_mapping中的key即使在params中，也作为需要保留的几何参数。
        """
        best_row = None
        best_dist = float("inf")

        for row in table:
            dist = 0.0
            match = True
            for key, target_val in params.items():
                if key in row:
                    dist += (row[key] - target_val) ** 2
                else:
                    match = False
                    break
            if match and dist < best_dist:
                best_dist = dist
                best_row = row

        if best_row is None:
            return None

        # 提取几何参数：
        # - 不在params中的字段直接保留（纯几何参数）
        # - 在param_mapping中的字段也保留（电气参数但需要映射为几何参数，如length_um→length）
        electrical_keys = set(params.keys()) - set(param_mapping.keys())
        geometry = {k: v for k, v in best_row.items() if k not in electrical_keys}

        return geometry

    def _check_constraints(self, geometry: dict, constraints: dict) -> list[str]:
        """检查几何参数是否在约束边界内。"""
        warnings = []
        for param_name, bounds in constraints.items():
            if param_name not in geometry:
                continue
            value = geometry[param_name]
            min_val = bounds.get("min")
            max_val = bounds.get("max")
            if min_val is not None and value < min_val:
                warnings.append(f"{param_name}={value} 低于下限 {min_val}")
            if max_val is not None and value > max_val:
                warnings.append(f"{param_name}={value} 超过上限 {max_val}")
        return warnings

    def map_all(self, targets: list[TargetParam]) -> list[MappedGeometry]:
        return [self.map(t) for t in targets]

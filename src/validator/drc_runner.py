"""KLayout DRC Runner：基于klayout.db的Region API实现DRC检查。

无需KLayout CLI，纯Python headless模式执行DRC。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import klayout.db as db
import yaml

from .base import BaseValidator, ValidationResult, Violation, Severity

logger = logging.getLogger(__name__)


@dataclass
class DRCRule:
    """单条DRC规则定义。"""
    name: str           # 规则名，如 "metal1.min_spacing"
    layer: str          # 层名，如 "metal1"
    check_type: str     # spacing / width / area / enclosure
    value: float        # 阈值 (um)
    severity: Severity = Severity.ERROR


class KLayoutDRCRunner(BaseValidator):
    """基于klayout.db Region API的DRC执行器。

    不依赖KLayout CLI，纯Python实现。
    """

    def run(self, gds_path: str, rules_path: str) -> ValidationResult:
        """运行DRC检查。

        Args:
            gds_path: GDS文件路径
            rules_path: DRC规则YAML文件路径

        Returns:
            ValidationResult
        """
        rules = self._load_rules(rules_path)
        report_path = str(gds_path).replace(".gds", "_drc_report.json")

        # 加载版图
        layout = db.Layout()
        layout.read(gds_path)

        violations = []

        for rule in rules:
            rule_violations = self._check_rule(layout, rule)
            violations.extend(rule_violations)

        passed = not any(v.severity == Severity.ERROR for v in violations)

        # 写报告
        self._write_report(report_path, violations)

        logger.info(
            f"DRC完成: {'PASS' if passed else 'FAIL'} "
            f"({len(violations)} 违例, "
            f"{sum(1 for v in violations if v.severity == Severity.ERROR)} 错误, "
            f"{sum(1 for v in violations if v.severity == Severity.WARNING)} 警告)"
        )

        return ValidationResult(
            passed=passed,
            violation_count=len(violations),
            violations=violations,
            report_path=report_path,
        )

    def _load_rules(self, rules_path: str) -> List[DRCRule]:
        """加载DRC规则YAML文件。"""
        path = Path(rules_path)
        content = path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)

        rules = []
        layer_map = data.get("layers", {})

        for rule_def in data.get("rules", []):
            severity = Severity.ERROR if rule_def.get("severity", "error") == "error" else Severity.WARNING
            rules.append(DRCRule(
                name=rule_def["name"],
                layer=rule_def["layer"],
                check_type=rule_def["type"],
                value=float(rule_def["value"]),
                severity=severity,
            ))

        return rules

    def _check_rule(self, layout: db.Layout, rule: DRCRule) -> List[Violation]:
        """执行单条DRC规则检查。"""
        # 获取层index
        layer_info = self._resolve_layer(layout, rule.layer)
        if layer_info is None:
            logger.warning(f"DRC规则 {rule.name}: 层 {rule.layer} 未找到，跳过")
            return []

        layer_idx = layer_info

        # 收集所有cell中的该层形状到Region
        region = db.Region()
        top_cell = layout.top_cell()
        if top_cell is None:
            return []

        # 递归收集所有子cell的形状（考虑变换）
        region = db.Region(top_cell.begin_shapes_rec(layer_idx))

        if region.is_empty():
            return []

        violations = []
        dbu = layout.dbu

        if rule.check_type == "spacing":
            # 间距检查：同层内形状间最小间距
            edge_pairs = region.space_check(int(rule.value / dbu))
            for ep in edge_pairs.each():
                center = (ep.first.bbox() + ep.second.bbox()).center()
                violations.append(Violation(
                    rule_name=rule.name,
                    severity=rule.severity,
                    layer=rule.layer,
                    x=center.x * dbu,
                    y=center.y * dbu,
                    description=f"间距 < {rule.value}um",
                ))

        elif rule.check_type == "width":
            # 线宽检查：形状最小宽度
            edge_pairs = region.width_check(int(rule.value / dbu))
            for ep in edge_pairs.each():
                bbox = ep.first.bbox()
                violations.append(Violation(
                    rule_name=rule.name,
                    severity=rule.severity,
                    layer=rule.layer,
                    x=bbox.center().x * dbu,
                    y=bbox.center().y * dbu,
                    description=f"线宽 < {rule.value}um",
                ))

        elif rule.check_type == "area":
            # 面积检查：形状最小面积
            min_area_dbu2 = int(rule.value / (dbu * dbu))
            for shape in region.each():
                area = shape.area()
                if area < min_area_dbu2:
                    bbox = shape.bbox()
                    violations.append(Violation(
                        rule_name=rule.name,
                        severity=rule.severity,
                        layer=rule.layer,
                        x=bbox.center().x * dbu,
                        y=bbox.center().y * dbu,
                        description=f"面积 {area * dbu * dbu:.1f}um² < {rule.value}um²",
                    ))

        elif rule.check_type == "not_empty":
            # 非空检查：层必须有内容
            if region.is_empty():
                violations.append(Violation(
                    rule_name=rule.name,
                    severity=rule.severity,
                    layer=rule.layer,
                    x=0, y=0,
                    description=f"层 {rule.layer} 为空",
                ))

        else:
            logger.warning(f"未知检查类型: {rule.check_type}")

        return violations

    def _resolve_layer(self, layout: db.Layout, layer_name: str) -> Optional[int]:
        """根据层名解析layer index。

        层名格式: "6/0" → layer=6, datatype=0
        也可以直接用层号。
        """
        # 格式: "layer/datatype"
        if "/" in layer_name:
            parts = layer_name.split("/")
            return layout.layer(int(parts[0]), int(parts[1]))

        # 尝试纯数字
        try:
            layer_num = int(layer_name)
            return layout.layer(layer_num, 0)
        except ValueError:
            pass

        return None

    def _write_report(self, report_path: str, violations: List[Violation]) -> None:
        """写DRC报告JSON。"""
        data = {
            "total_violations": len(violations),
            "errors": sum(1 for v in violations if v.severity == Severity.ERROR),
            "warnings": sum(1 for v in violations if v.severity == Severity.WARNING),
            "violations": [
                {
                    "rule": v.rule_name,
                    "severity": v.severity.value,
                    "layer": v.layer,
                    "x": round(v.x, 3),
                    "y": round(v.y, 3),
                    "description": v.description,
                    "related_refs": v.related_refs,
                }
                for v in violations
            ],
        }
        Path(report_path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

"""DRC违例坐标→器件Reference关联映射。"""

from __future__ import annotations

from typing import Dict, List, Tuple

import klayout.db as db

from .base import Violation


class ViolationRefMapper:
    """将DRC违例坐标映射到器件Reference。

    原理：每个器件在版图中有包围盒，违例坐标落在器件包围盒附近（含容差）则关联。
    """

    def __init__(
        self,
        device_bboxes: Dict[str, Tuple[float, float, float, float]],
        tolerance: float = 10.0,
    ):
        """
        Args:
            device_bboxes: {reference: (x1, y1, x2, y2)} 单位um
            tolerance: 包围盒扩展容差 (um)
        """
        self.bboxes = device_bboxes
        self.tolerance = tolerance

    def map_violations(self, violations: List[Violation]) -> List[Violation]:
        """为每条违例关联可能的器件。"""
        for v in violations:
            related = []
            for ref, (x1, y1, x2, y2) in self.bboxes.items():
                if (x1 - self.tolerance <= v.x <= x2 + self.tolerance and
                    y1 - self.tolerance <= v.y <= y2 + self.tolerance):
                    related.append(ref)
            v.related_refs = related if related else None
        return violations

    @classmethod
    def from_layout(
        cls,
        layout: db.Layout,
        tolerance: float = 10.0,
    ) -> ViolationRefMapper:
        """从当前版图中提取所有子cell的包围盒构建mapper。

        Args:
            layout: KLayout Layout对象
            tolerance: 包围盒扩展容差 (um)

        Returns:
            ViolationRefMapper实例
        """
        dbu = layout.dbu
        bboxes: Dict[str, Tuple[float, float, float, float]] = {}
        top_cell = layout.top_cell()

        if top_cell is None:
            return cls({}, tolerance)

        for inst in top_cell.each_inst():
            cell = inst.cell
            # 提取reference：cell名中第一个_前的部分，或整个名
            ref = cell.name.split("_")[0] if "_" in cell.name else cell.name

            # 计算cell在top_cell中的全局bbox
            inst_trans = inst.trans
            cell_bbox = cell.bbox()
            # 变换到全局坐标
            global_bbox = inst_trans * cell_bbox

            x1 = global_bbox.left * dbu
            y1 = global_bbox.bottom * dbu
            x2 = global_bbox.right * dbu
            y2 = global_bbox.top * dbu

            bboxes[ref] = (x1, y1, x2, y2)

        return cls(bboxes, tolerance)

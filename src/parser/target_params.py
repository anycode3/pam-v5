"""目标参数文件解析器。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TargetParam:
    """单个器件的目标参数。"""
    reference: str           # 器件reference，如 C1
    device_type: str         # 器件类型，如 capacitor_mim
    params: dict             # 目标电气参数，如 {"capacitance_pf": 2.0}


class TargetParamsParser:
    """解析优化算法输出的目标参数JSON文件。"""

    def parse(self, path: str | Path) -> list[TargetParam]:
        """解析目标参数文件。

        Args:
            path: JSON文件路径

        Returns:
            目标参数列表
        """
        path = Path(path)
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)

        results = []
        for item in data:
            results.append(TargetParam(
                reference=item["reference"],
                device_type=item["type"],
                params=item["params"],
            ))
        return results

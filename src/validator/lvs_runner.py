"""KLayout 纯 Python LVS 执行器。

使用 klayout.db Region.merge() + interacting() 提取连通性，
与 KiCad 网表进行集合比对，检测 OPEN/SHORT 违例。
"""

from __future__ import annotations

import klayout.db as db
from typing import Dict, List, Set, Tuple

from .base import BaseLVSRunner, LVSResult


class KLayoutPureLVS(BaseLVSRunner):
    """基于 klayout.db Region 的简化 LVS。

    算法：
    1. 将所有金属层和通孔层的 shapes 合并为一个 Region
    2. 对每个引脚坐标，用 2um 查询框 + interacting() 找到所属连通区域
    3. 将 schematic_nets 与 physical_nets 进行集合比对，检出 OPEN/SHORT
    """

    # 参与连通的金属层 (layer, datatype)
    METAL_LAYERS: List[Tuple[int, int]] = [(6, 0), (7, 0)]
    # 通孔层
    VIA_LAYERS: List[Tuple[int, int]] = [(11, 0)]

    def run(
        self,
        gds_path: str,
        schematic_nets: Dict[str, List[str]],
        pin_positions: Dict[str, Tuple[float, float]],
    ) -> LVSResult:
        """执行 LVS 比对。

        Args:
            gds_path: GDS 文件路径
            schematic_nets: KiCad 解析得到的网表连接 {net_name: [ref.pin_name, ...]}
            pin_positions: {ref.pin_name: (x_um, y_um)} 引脚全局坐标

        Returns:
            LVSResult
        """
        layout = db.Layout()
        layout.read(gds_path)
        top_cell = layout.top_cell()
        if top_cell is None:
            return LVSResult(passed=False)

        dbu = layout.dbu

        # ── 1. 构建合并 Region ──────────────────────────────────────
        merged_region = db.Region()
        for layer_info in self.METAL_LAYERS + self.VIA_LAYERS:
            layer_idx = layout.layer(db.LayerInfo(layer_info[0], layer_info[1]))
            if layer_idx < 0:
                continue
            # 从top cell递归收集shapes（含instance变换到全局坐标）
            region_from_shapes = db.Region(top_cell.begin_shapes_rec(layer_idx))
            if not region_from_shapes.is_empty():
                merged_region += region_from_shapes

        if merged_region.is_empty():
            # 无任何金属 shapes，所有引脚都悬空
            result = LVSResult(passed=False)
            for net_name, pins in schematic_nets.items():
                result.add_open(net_name, set(pins), set())
            return result

        merged_region.merge()

        # ── 2. 构建引脚 → 连通区域映射 ─────────────────────────────
        # 先将 merged_region 打散为独立 region list（保持有序 id）
        region_list: List[db.Region] = []
        for poly in merged_region.each():
            region_list.append(db.Region(poly))

        pin_to_region: Dict[str, int] = {}  # pin_name → region_id (None=悬空)
        physical_nets: Dict[int, Set[str]] = {}  # region_id → {pin_name, ...}

        for pin_name, (px, py) in pin_positions.items():
            # 2um x 2um 查询框（容许亚微米浮点误差）
            query_box = db.Box(
                int((px - 1.0) / dbu), int((py - 1.0) / dbu),
                int((px + 1.0) / dbu), int((py + 1.0) / dbu)
            )
            point_region = db.Region(query_box)

            # interacting: 查询框与哪些 region 有物理接触
            connected = point_region.interacting(merged_region)

            if connected.is_empty():
                pin_to_region[pin_name] = None  # 悬空引脚
                continue

            # 找到 connected 属于哪个 region id
            found_rid = None
            for rid, region in enumerate(region_list):
                if not (connected & region).is_empty():
                    found_rid = rid
                    physical_nets.setdefault(rid, set()).add(pin_name)
                    break

            pin_to_region[pin_name] = found_rid

        # ── 3. 比对 schematic_nets vs physical_nets ─────────────────
        result = LVSResult(passed=True, physical_nets={
            rid: pins for rid, pins in physical_nets.items()
        })

        for net_name, expected_pins in schematic_nets.items():
            if not expected_pins:
                continue
            expected_set = set(expected_pins)

            # 取网表中第一个引脚，找到它所属的 region
            first_pin = expected_pins[0]
            region_id = pin_to_region.get(first_pin)

            if region_id is None:
                # 第一个引脚就悬空 → 全网悬空
                result.add_open(net_name, expected_set, set())
                continue

            actual_set = physical_nets.get(region_id, set())

            # OPEN：期望的引脚不全在同一个 region
            missing = expected_set - actual_set
            if missing:
                result.add_open(net_name, expected_set, actual_set)

            # SHORT：该 region 中有不该在该网表中的引脚
            extra = actual_set - expected_set
            if extra:
                result.add_short(net_name, extra)

        return result

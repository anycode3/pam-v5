# LVS 设计规格

## 1. 目标与范围

### 1.1 目标
为 PAM V2.0 工具链提供 Layout vs. Schematic 电气正确性验证，检测 StretchRouter 拉伸后连线是否与网表一致。

### 1.2 覆盖范围
- **RF 无源电路 LVS**：L-match、滤波器等无源器件电路
- 开路检测（OPEN）：网表中要求连通的引脚对在 GDS 中是否物理连通
- 短路检测（SHORT）：网表中要求断开的引脚对在 GDS 中是否意外连通
- 器件匹配：GDS 中器件 reference 和参数是否与网表对应

### 1.3 不覆盖范围
- 晶体管级参数比对（W/L 比率、mosfet 阈值）
- 寄生参数提取（RLC 寄生）
- 功耗分析
- 时序分析

### 1.4 架构原则
- **抽象接口**：定义 `BaseLVSRunner`，未来可切换到 Netgen
- **零外部依赖**：纯 Python + klayout.db 实现，可立即运行
- **最小化系统依赖**：仅依赖 klayout.db（已可用）

---

## 2. 算法

### 2.1 连通性提取
使用 `klayout.db.Region.merge()` 将所有金属层和通孔层的几何合并，形成独立的连通区域（connected region）。

```python
merged_region = Region()
for layer_info in metal_layers + via_layers:
    layer_idx = layout.layer(LayerInfo(*layer_info))
    merged_region += Region(cell.shapes(layer_idx))
merged_region.merge()
```

### 2.2 引脚归属查询（C1 方案）
对于每个引脚坐标，用 `interacting()` 确认它落在哪个连通区域内：

```python
# 2um x 2um 查询框（容许亚微米浮点误差）
query_box = Box(
    int((px - 1.0) / dbu), int((py - 1.0) / dbu),
    int((px + 1.0) / dbu), int((py + 1.0) / dbu)
)
point_region = Region(query_box)
connected = point_region.interacting(merged_region)
```

语义：`interacting` 问的是"这个查询框与哪些 region 有物理接触"，而非 `contains` 的"是否严格在多边形内部"。因此即使引脚 marker 边界与走线边缘相切也能正确检出。

### 2.3 集合比对
- 从 KiCad 网表解析得到 `schematic_nets: {net_name: [ref.pin_name, ...]}`
- 从 GDS 提取得到 `physical_nets: {region_id: [ref.pin_name, ...]}`
- 判定规则：
  - **OPEN**：`expected_pins` 中有引脚不在 `actual_pins` 中
  - **SHORT**：`actual_pins` 中有引脚不在 `expected_pins` 中
  - **MISMATCH**：引脚数量不一致

---

## 3. 数据流

### 3.1 输入
| 输入 | 来源 |
|------|------|
| GDS 文件路径 | `Runner._config.output_path` |
| schematic_nets | `KiCadNetlistParser.parse()` 得到的 nets |
| pin_positions | `ParamsSnapshot.devices[ref].pins` |

### 3.2 输出
`LVSResult`：
```python
@dataclass
class LVSResult:
    passed: bool
    violations: List[LVSViolation]
    physical_nets: Dict[int, Set[str]]  # region_id → pin_names

@dataclass
class LVSViolation:
    violation_type: str   # "OPEN" | "SHORT" | "MISMATCH"
    net_name: str
    expected_pins: Set[str]
    actual_pins: Set[str]
    description: str
```

### 3.3 数据流图
```
KiCad Netlist ──Parser──> nets ──┐
                                  ├──> LVS比对 ──> LVSResult
ParamsSnapshot ────────────────────┘
                   pin_positions ──┘
```

---

## 4. 集成点

### 4.1 Runner 集成
在 `core/runner.py` 的 `_execute_with_drc_loop()` 中，DRC 通过后执行 LVS：

```
DRC通过 → LVS验证 → LVS通过 → 成功返回
                    └─ LVS失败 → 回滚GDS → 返回错误（不重试）
```

LVS 失败不重试的原因：LVS 反映的是物理连接错误，参数 shrink 无法修正。

### 4.2 抽象接口
```python
# validator/base.py
class BaseLVSRunner(ABC):
    @abstractmethod
    def run(
        self,
        gds_path: str,
        schematic_nets: Dict[str, List[str]],  # {net: [pin, ...]}
        pin_positions: Dict[str, Tuple[float, float]],  # {ref.pin: (x, y)}
    ) -> LVSResult:
        pass
```

### 4.3 配置控制
```python
# core/runner.py
@dataclass
class RunConfig:
    # ...
    lvs_enabled: bool = False
```

### 4.4 实现类
- `validator/klayout_lvs_runner.py`：`KLayoutPureLVS`（当前实现）
- `validator/netgen_lvs_runner.py`：`NetgenLVSRunner`（未来实现，预留接口）

---

## 5. 引脚定位策略

### 5.1 PIN_MARKER_LAYER 约定
每个 PCell 在 `generate()` 时必须在引脚位置画出 pin marker：

```python
# pcells/base.py
PIN_MARKER_LAYER: Tuple[int, int] = (255, 0)  # 供 LVS 提取用

def _draw_pin_marker(self, cell, pin_name: str, x: float, y: float, size: float = 2.0):
    """在引脚位置画一个 2um 的 marker，供 LVS 提取连通性用。"""
    dbu = cell.layout().dbu
    half = int(size / 2.0 / dbu)
    cx = int(x / dbu)
    cy = int(y / dbu)
    marker_layer = cell.layout().layer(LayerInfo(*self.PIN_MARKER_LAYER))
    cell.shapes(marker_layer).insert(
        Box(cx - half, cy - half, cx + half, cy + half)
    )
```

### 5.2 悬空引脚处理
如果引脚 marker 与任何金属层均无接触（`interacting` 返回空），则该引脚为悬空，视为 OPEN 违例。

### 5.3 已有 PCell 补齐
在实现 LVS 前，先为三个已有 PCell 补上 `_draw_pin_marker` 调用：
- `CAP_MIM`：PI 和 NIN 各一个 marker
- `TL_MICROSTRIP`：P1 和 P2 各一个 marker
- `IND_SPIRAL`：PI 和 NIN 各一个 marker

---

## 6. 比对算法

### 6.1 流程
```
1. Region.merge() → merged_region（所有连通区域）
2. 对每个 schematic_net：
   a. 取第一个引脚坐标，用 interacting() 找到所属 region_id
   b. 获取该 region 内所有引脚（actual_pins）
   c. expected_pins vs actual_pins → OPEN/SHORT 判定
```

### 6.2 OPEN 判定
```python
missing = expected_set - actual_set
if missing:
    result.add_open(net_name, expected_set, actual_set)
```

### 6.3 SHORT 判定
```python
extra = actual_set - expected_set
if extra:
    result.add_short(net_name, extra)
```

### 6.4 多引脚同 Net
支持一个 net 包含 2 个以上引脚（如 `C1.PI` 和 `TL1.P2` 同属 `NET_C1_TL1`）。比对时取第一个引脚定位 region，再检查其他引脚是否在同一 region 内。

---

## 7. Netgen 接口预留

### 7.1 抽象基类签名
```python
class BaseLVSRunner(ABC):
    @abstractmethod
    def run(self, gds_path, schematic_nets, pin_positions) -> LVSResult:
        pass

    def supports_device_check(self) -> bool:
        """Netgen 可做器件参数精细比对，纯 Python LVS 不支持。"""
        return False
```

### 7.2 未来 Netgen 对接方式
```
NetgenLVSRunner.run():
  1. 从 GDS 提取 SPICE netlist（KLayout 内置功能）
  2. subprocess.call(["netgen", "-batch", "compare", ...])
  3. 解析 netgen 输出日志 → LVSResult
  4. 通过 BaseLVSRunner 接口返回
```

切换实现类只需改 Runner 构造函数：
```python
self._lvs_runner = (
    NetgenLVSRunner() if config.lvs_enabled and self._detect_netgen() else KLayoutPureLVS()
)
```

---

## 8. 测试清单

### 8.1 LVS 冒烟测试（validator/）
| 测试 | 场景 | 预期结果 |
|------|------|----------|
| `test_lvs_pass` | 正确连线，无违例 | PASS |
| `test_lvs_open` | 删除一段走线 | OPEN 检出 |
| `test_lvs_short` | 添加一段桥接线 | SHORT 检出 |
| `test_lvs_multi_pin` | 多引脚同 net | 一致性检查通过 |
| `test_lvs_dangling` | 悬空引脚 | OPEN 检出 |
| `test_lvs_abstract_interface` | BaseLVSRunner 接口 | 可替换实现类 |

### 8.2 全链路集成测试
| 测试 | 场景 | 预期结果 |
|------|------|----------|
| `test_lvs_after_drc` | DRC 通过后自动执行 LVS | LVS PASS → 输出 GDS |
| `test_lvs_failure_rollback` | LVS 失败 | GDS 回滚，无输出 |
| `test_lvs_with_stretch` | 带 StretchRouter 的完整迭代 | 连线拉伸后 LVS 仍 PASS |

### 8.3 回归测试
- 现有 54 个测试全部通过
- LVS 关闭时行为不变（`lvs_enabled=False`）

---

## 9. 文件结构

```
src/validator/
    base.py           # BaseLVSRunner 抽象基类，LVSResult/LVSViolation 数据类
    lvs_runner.py     # KLayoutPureLVS 实现（新增）
    netgen_lvs_runner.py  # NetgenLVSRunner 预留（新增，注释实现）

state/snapshot_manager.py  # 已有，ParamsSnapshot 复用

pcells/base.py     # 补 _draw_pin_marker 约定
pcells/mim_capacitor/pcell.py
pcells/transmission_line/pcell.py
pcells/spiral_inductor/pcell.py  # 各补 pin marker 绘制

tests/fixtures/l_match/
    initial_layout.gds  # 已有（带 pin markers）
```

---

## 10. 实施顺序

1. **补 PIN_MARKER_LAYER**：为 3 个 PCell 补 `_draw_pin_marker` 调用
2. **重建 fixture**：重新生成 `initial_layout.gds`（含 marker 层）
3. **LVS 数据结构**：`validator/base.py` 新增 `LVSResult`、`LVSViolation`、`BaseLVSRunner`
4. **KLayoutPureLVS**：`validator/lvs_runner.py` 实现 `run()` 方法
5. **Runner 集成**：在 `_execute_with_drc_loop` 中 DRC 通过后调用 LVS
6. **测试**：LVS 冒烟测试 + 全链路集成测试

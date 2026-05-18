# PAM — RF 无源电路版图迭代自动化引擎

PAM (Parameterized Auto-layout Manager) 是一个 RF 无源电路版图迭代自动化工具。当电路仿真发现器件参数需要调整时，PAM 自动完成从电气参数到版图几何的映射、PCell 更新、连线重绘和 DRC/LVS 验证，避免手动改版图的繁琐流程。

## 处理流程总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          PAM 处理流程                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  输入:                                                                  │
│  ┌──────────┐  ┌───────────────┐  ┌────────────────┐                   │
│  │ 当前GDS  │  │ 原始网表.net  │  │ 修改后网表.net  │                   │
│  └────┬─────┘  └──────┬────────┘  └───────┬────────┘                   │
│       │               │                   │                             │
│       │        ┌──────┴───────────────────┴──────┐                      │
│       │        │     1. 网表解析 + 差异比较       │                      │
│       │        │  parser.parse() → Component,Net  │                      │
│       │        │  diff_netlists() → DeviceDiff    │                      │
│       │        └──────────────┬───────────────────┘                      │
│       │                       │ 变更器件列表                             │
│       │        ┌──────────────┴───────────────────┐                      │
│       │        │  2. 电气参数 → 几何参数映射       │                      │
│       │        │  parse_value() → 电气参数         │                      │
│       │        │  MappingEngine.map() → 几何参数   │  ← mapping_rules.yaml │
│       │        └──────────────┬───────────────────┘                      │
│       │                       │ MappedGeometry[]                         │
│       │        ┌──────────────┴───────────────────┐                      │
│       ├───────►│  3. 版图更新                      │                      │
│       │        │  a. 提取旧连线 (wire_extractor)   │                      │
│       │        │  b. 更新PCell几何 (pcell.generate)│                      │
│       │        │  c. 擦除旧连线                     │                      │
│       │        │  d. 重绘新连线 (initial_router)    │                      │
│       │        └──────────────┬───────────────────┘                      │
│       │                       │ 更新后的GDS                              │
│       │        ┌──────────────┴───────────────────┐                      │
│       │        │  4. DRC/LVS 验证                  │  ← drc_rules.yaml  │
│       │        │  失败则回退+缩小几何+重试          │                      │
│       │        └──────────────┬───────────────────┘                      │
│       │                       │                                          │
│  ┌────┴─────┐                                                          │
│  │ 输出GDS  │  + 运行报告                                               │
│  └──────────┘                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 模块详解

### 1. parser — 网表解析模块

负责解析 KiCad S-expression 格式的网表文件，提取器件和网络连接信息，并对比两个网表找出差异。

#### 文件结构

| 文件 | 职责 |
|------|------|
| `base.py` | 抽象基类 `NetlistParser`，定义统一接口 |
| `types.py` | 公共数据类 `Component`、`Net` |
| `factory.py` | 工厂路由 `NetlistRouter`，支持自动格式检测 |
| `kicad_netlist.py` | KiCad 格式解析器实现 |
| `value_parser.py` | 器件值字符串解析（"1pF" → `{"capacitance_pf": 1.0}`） |
| `target_params.py` | JSON 目标参数文件解析 |
| `netlist_diff.py` | 两个网表的差异比较 |
| `exceptions.py` | 异常层次：`NetlistParseError` → `UnsupportedFormatError` / `FormatDetectionError` |

#### 核心数据结构

```python
@dataclass
class Component:
    reference: str       # 位号，如 "C1"
    value: str           # 值，如 "1pF"
    name: str            # 器件类型，如 "CAP_MIM"
    lib: str             # KiCad 库源
    ext: dict            # 格式扩展字段（如 footprint）

@dataclass
class Net:
    name: str                         # 网络名，如 "NET_C1_L1"
    nodes: list[tuple[str, str]]      # [(位号, 引脚名), ...]
    ext: dict                         # 格式扩展字段
```

#### 核心函数

| 函数 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `KiCadNetlistParser.parse(path)` | `.net` 文件路径 | `(List[Component], List[Net])` | 解析 KiCad 网表 |
| `NetlistRouter.parse(path)` | 任意格式网表路径 | `(List[Component], List[Net])` | 自动检测格式并路由 |
| `parse_value(part_name, value_str)` | `"CAP_MIM"`, `"1pF"` | `{"capacitance_pf": 1.0}` | 器件值字符串 → 电气参数字典 |
| `value_to_device_type(part_name)` | `"CAP_MIM"` | `"capacitor_mim"` | KiCad 器件名 → 映射规则 key |
| `diff_netlists(orig, modified)` | 两组 `Component` 列表 | `NetlistDiffResult` | 对比差异：值变更/类型变更/增删 |

#### 扩展机制

通过 `@register_parser("format_name")` 装饰器注册新格式解析器，`NetlistRouter` 自动根据文件扩展名和内容路由到对应解析器。当前支持：`.net` / `.sexp` → KiCad。

---

### 2. mapper — 映射引擎模块

将电气参数（电容值、电感值、阻抗/长度）映射为 PCell 几何参数（长宽、半径、圈数等），通过查表 + 最近邻匹配实现。

#### 文件结构

| 文件 | 职责 |
|------|------|
| `engine.py` | `MappingEngine` 查表映射 + 约束检查 |

#### 核心数据结构

```python
@dataclass
class MappedGeometry:
    reference: str          # 位号，如 "C1"
    target_pcell: str       # 目标 PCell 名，如 "CAP_MIM"
    geometry_params: dict   # 几何参数，如 {"length": 57, "width": 57}
    constraints: dict       # 约束边界，如 {"length": {"min": 10, "max": 200}}
    warnings: list[str]     # 越界警告
```

#### 核心函数

| 函数 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `MappingEngine(rules_path).__init__` | `mapping_rules.yaml` 路径 | — | 加载映射规则 |
| `MappingEngine.map(target)` | `TargetParam(reference, device_type, params)` | `MappedGeometry` | 电气参数 → 几何参数 |
| `MappingEngine.map_all(targets)` | `List[TargetParam]` | `List[MappedGeometry]` | 批量映射 |

#### 映射流程

```
电气参数 (e.g., capacitance_pf=2.0)
    │
    ▼  1. 在 lookup_table 中按欧氏距离找最近邻行
    │
    ▼  2. 应用 param_mapping 重命名字段 (length_um → length)
    │
    ▼  3. 填充 defaults (spacing=8.0, angle=0.0)
    │
    ▼  4. 约束检查 (constraints 中 min/max)
    │     缺失约束 → 不检查（通过）
    │     越界 → 记入 warnings，不阻断
    ▼
几何参数 (e.g., {length: 57, width: 57})
```

#### 映射规则配置 (`config/mapping_rules.yaml`)

```yaml
capacitor_mim:
  target_pcell: "CAP_MIM"
  param_mapping:          # 查表结果字段 → PCell 参数名
    length: length
    width: width
  defaults: {}            # 默认值补充
  constraints:            # 几何参数边界
    length: { min: 10, max: 200 }
    width:  { min: 10, max: 200 }
  lookup_table:           # 电气值 → 几何值 查找表
    - { capacitance_pf: 0.5, length: 28,  width: 28  }
    - { capacitance_pf: 1.0, length: 40,  width: 40  }
    - { capacitance_pf: 2.0, length: 57,  width: 57  }
    ...
```

---

### 3. routing — 布线模块

负责从 GDS 中提取旧引脚坐标、旧连线，以及在版图更新后重新布线。

#### 文件结构

| 文件 | 职责 |
|------|------|
| `types.py` | 布线数据类：`PinState`、`WireSegment`、`Connection`、`StretchResult` |
| `base.py` | 布线策略抽象基类 + `StretchRouter` 实现 |
| `pin_extractor.py` | 从 GDS sub-cell 的 PIN marker 层提取引脚绝对坐标 |
| `wire_extractor.py` | 从 GDS top cell 提取金属连线并关联到网络 |
| `wire_finder.py` | 根据网表连接关系发现引脚间连线 |
| `initial_router.py` | 初始布线器：两点间直线/L型布线 |

#### 核心数据结构

```python
@dataclass
class PinState:
    name: str             # 引脚名，如 "PI"
    ref: str              # 位号，如 "C1"
    x: float              # 绝对 X 坐标 (um)
    y: float              # 绝对 Y 坐标 (um)

@dataclass
class WireSegment:
    layer: Tuple[int,int]       # (层号, 数据类型)，如 (6, 0)
    points: List[Tuple[float,float]]  # 路径顶点 (um)
    width: float                # 线宽 (um)

@dataclass
class Connection:
    net_name: str
    pin_a: PinState           # 起始引脚
    pin_b: PinState           # 终止引脚
    wires: List[WireSegment]  # 连接线段
```

#### 核心函数

| 函数 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `extract_pin_positions(layout, top_cell)` | KLayout Layout, Top Cell | `{ref: {pin: (x,y)}}` | 提取所有器件引脚绝对坐标 |
| `extract_pin_layers(layout, top_cell)` | KLayout Layout, Top Cell | `{ref: {pin: (layer,dt)}}` | 引脚所在金属层 |
| `extract_wires_from_gds(layout, top_cell, nets)` | Layout, Top Cell, 网表网络 | `{net: [WireSegment]}` | 提取连线并关联到网络 |
| `erase_wires_from_top_cell(layout, top_cell, nets, wires)` | 同上 | — | 擦除指定网络的连线 |
| `InitialRouter.route_all(...)` | Layout, nets, ref_to_pcell, ... | `{net: [WireSegment]}` | 全量布线 |
| `InitialRouter.route_affected_nets(...)` | 同上 + changed_refs | `{net: [WireSegment]}` | 仅对受影响网络布线 |
| `draw_wire_segments(cell, layout, wires)` | Cell, Layout, [WireSegment] | — | 将 WireSegment 绘制为 GDS 几何 |
| `StretchRouter.stretch_connections(...)` | Layout, Cell, connections, ... | `StretchResult` | 微调连线（位移 < 100um 时拉伸，否则标记 BROKEN） |

#### 连线提取原理

1. 从 top cell 收集所有金属层 Shape（排除 PIN marker 层 255/0）
2. 调用 `extract_pin_positions()` 获取每个引脚的绝对坐标
3. 对每个 Shape 构造 BoundingBox，检查哪些引脚落在 Box 内
4. 通过网表的 `pin_to_net` 反向索引将 Shape 归属到对应网络
5. 将 Shape 转换为 `WireSegment`（水平/垂直方向判定）

#### 引脚提取原理

GDS 中每个器件 sub-cell 内的 PIN marker 层 (255/0) 放置了文本标签，标签名即为引脚名。PAM 遍历 top cell 下的所有 instance，对每个 instance：
1. 找到其对应的 sub-cell
2. 读取 sub-cell 中 255/0 层的文本标签
3. 用 `instance.dcplx_trans` 将局部坐标转换为全局坐标

Cell 命名约定：`{位号}_{PCell名}`，如 `C1_CAP_MIM` → 位号 `C1`。

---

### 4. core — 核心运行模块

编排整个处理流程：网表解析 → 差异比较 → 映射 → 版图更新 → 验证。

#### 文件结构

| 文件 | 职责 |
|------|------|
| `cli.py` | 命令行入口，解析参数 |
| `runner.py` | 核心编排器 `Runner`，串联所有模块 |

#### 核心数据结构

```python
@dataclass
class RunConfig:
    gds_path: str                   # 输入 GDS
    netlist_path: str               # 原始网表
    modified_netlist_path: str      # 修改后网表
    pdk_config_path: str            # PDK 配置路径
    output_path: str = "output.gds"
    drc_enabled: bool = True
    drc_max_retries: int = 3
    drc_shrink_factor: float = 0.9
    lvs_enabled: bool = False

@dataclass
class RunResult:
    success: bool
    diff_result: Optional[NetlistDiffResult]
    mapped_geometries: list[MappedGeometry]
    execution_result: Optional[ExecutionResult]
    drc_result: Optional[ValidationResult]
    lvs_result: Optional[LVSResult]
    errors: list[str]
    duration_s: float
```

#### Runner.run() 详细流程

```
Runner.run()
 │
 ├── 1. 解析原始网表          KiCadNetlistParser.parse(netlist_path)
 ├── 2. 解析修改后网表        KiCadNetlistParser.parse(modified_netlist_path)
 ├── 3. 差异比较              diff_netlists() → NetlistDiffResult
 │
 ├── 4. 映射变更器件          _map_changed_devices()
 │   ├── parse_value()        "2pF" → {"capacitance_pf": 2.0}
 │   ├── value_to_device_type()  "CAP_MIM" → "capacitor_mim"
 │   └── MappingEngine.map()  → MappedGeometry (几何参数 + 约束)
 │
 ├── 5. 备份 GDS              GDSBackupManager.save_backup()
 │
 ├── 6. 更新版图              _update_layout()
 │   ├── 加载 GDS Layout
 │   ├── extract_wires_from_gds()      提取旧连线
 │   ├── PCell.validate_params()       约束校验（失败则跳过该器件）
 │   ├── pcell.generate(cell, params)  重新生成 sub-cell 几何
 │   ├── erase_wires_from_top_cell()   擦除受影响网络的旧连线
 │   ├── InitialRouter.route_affected_nets()  计算新布线
 │   ├── draw_wire_segments()          绘制新连线
 │   └── 保存更新后的 GDS
 │
 ├── 7. DRC 验证              _run_drc_with_retry()
 │   ├── KLayoutDRCRunner.run()
 │   ├── 失败 → 恢复备份 → 几何缩小 shrink_factor → 重试
 │   └── 最多重试 drc_max_retries 次
 │
 ├── 8. LVS 验证（可选）      _run_lvs()
 │   └── KLayoutPureLVS.run()
 │
 └── 9. 记录历史              _append_history() → JSONL
```

#### CLI 参数

```
pam run \
  --gds <GDS路径>                 # 必填：当前版图文件
  --netlist <原始网表>             # 必填：与当前版图对应的网表
  --modified-netlist <新网表>      # 必填：修改后的网表
  --pdk-config <YAML路径>          # 可选：PDK配置（默认 config/mapping_rules.yaml）
  --output <输出路径>              # 可选：输出 GDS（默认 output.gds）
  --state-dir <目录>              # 可选：状态目录（默认 state）
  --history <文件>                # 可选：历史记录文件
  --no-drc                        # 可选：跳过 DRC 检查
  --lvs                           # 可选：启用 LVS 验证
  -v                              # 可选：详细日志输出
```

---

### 5. validator — 验证模块

执行 DRC（设计规则检查）和 LVS（版图与原理图一致性检查）。

#### 文件结构

| 文件 | 职责 |
|------|------|
| `base.py` | 数据类 `Violation`、`ValidationResult`、`LVSResult` + 抽象基类 |
| `drc_runner.py` | KLayout DRC 执行器 |
| `ref_mapper.py` | DRC 违例 → 器件位号映射 |
| `lvs_runner.py` | 纯 Python LVS 执行器 |

#### DRC 执行流程

```
KLayoutDRCRunner.run(gds_path, rules_path)
 │
 ├── 1. 加载 DRC 规则 (YAML)
 │     规则类型: spacing / width / area / not_empty
 │
 ├── 2. 加载 GDS Layout
 │
 ├── 3. 对每条规则:
 │   ├── 收集该层所有 Shape → Region
 │   ├── spacing: region.space_check(value)
 │   ├── width:   region.width_check(value)
 │   ├── area:    逐个检查 shape.area() ≥ value
 │   └── not_empty: 检查 region 非空
 │
 ├── 4. ViolationRefMapper 将违例坐标映射到器件位号
 │
 └── 5. 输出 ValidationResult + JSON 报告
```

#### LVS 执行流程

```
KLayoutPureLVS.run(gds_path, schematic_nets, pin_positions)
 │
 ├── 1. 收集所有金属层 + 通孔层 Shape → 合并为 Region
 │
 ├── 2. 对每个引脚:
 │   ├── 构造 2um×2um 查询框
 │   └── Region.interacting() 找到连通区域 → region_id
 │
 ├── 3. 构建 physical_nets: {region_id: {pin_names}}
 │
 └── 4. 与 schematic_nets 对比:
       ├── OPEN: 同一网络引脚不在同一连通区域
       └── SHORT: 同一连通区域包含不同网络的引脚
```

#### 核心数据结构

```python
@dataclass
class Violation:
    rule_name: str          # 规则名，如 "metal1.min_spacing"
    severity: Severity      # ERROR / WARNING
    layer: str              # 层名，如 "6/0"
    x: float                # 违例中心 X (um)
    y: float                # 违例中心 Y (um)
    description: str
    related_refs: list[str] # 关联的器件位号

@dataclass
class ValidationResult:
    passed: bool
    violation_count: int
    violations: List[Violation]
    report_path: str

@dataclass
class LVSResult:
    passed: bool
    violations: List[LVSViolation]  # OPEN / SHORT / MISMATCH
    physical_nets: Dict[int, Set[str]]
```

---

### 6. pcells — 参数化单元模块

定义 RF 无源器件的版图生成规则，每个 PCell 知道如何根据几何参数绘制 GDS 图形。

#### 文件结构

| 文件 | 职责 |
|------|------|
| `base.py` | 抽象基类 `BasePCell`，定义统一接口 |
| `registry.py` | PCell 注册表 `@register("NAME")` |
| `mim_capacitor/pcell.py` | MIM 电容器 PCell |
| `spiral_inductor/pcell.py` | 螺旋电感器 PCell |
| `transmission_line/pcell.py` | 微带传输线 PCell |

#### PCell 接口

```python
class BasePCell(ABC):
    def get_parameters(self) -> Dict[str, str]       # {"length": "float:um"}
    def get_pins(self) -> List[str]                   # ["PI", "NIN"]
    def get_pin_positions(self, params) -> Dict[str, PinPosition]
    def generate(self, cell: db.Cell, params: dict)   # 生成几何图形
    def validate_params(self, params, constraints=None) -> (bool, List[str])
    def get_bounding_box(self, params) -> Tuple[float,float,float,float]
    def get_required_layers(self) -> Dict[str, Tuple[int,int]]
```

#### 三个 PCell 详情

| PCell | 注册名 | 参数 | 引脚 | 层结构 |
|-------|--------|------|------|--------|
| MIM 电容 | `CAP_MIM` | `length`, `width` | PI (上极板), NIN (下极板) | MT(10/0), MB(8/0), MIM(9/0), VIA(9/1) |
| 螺旋电感 | `IND_SPIRAL` | `inner_radius`, `turns`, `width`, `spacing`, `angle` | PI (外端), NIN (底端underpass) | MT(7/0), MU(6/0), VIA(11/0) |
| 微带线 | `TL_MICROSTRIP` | `width`, `length`, `angle` | P1 (输入), P2 (输出) | METAL(6/0), GND(2/0) |

#### PIN Marker 层

所有 PCell 在 `255/0` 层绘制文本标签作为引脚标记，用于：
- LVS 连通性提取时定位引脚
- 版图更新时提取旧引脚坐标

#### 约束校验机制

`validate_params(params, constraints)` 接收来自 YAML 的约束字典：
- 约束缺失 → 该参数不检查，直接通过
- 约束存在但越界 → 返回 `(False, [错误信息])`，Runner 跳过该器件更新
- 全部通过 → 返回 `(True, [])`

---

### 7. state — 状态管理模块

负责 GDS 文件备份和恢复，用于 DRC 失败时回退到更新前状态。

| 函数 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `GDSBackupManager.save_backup(gds_path)` | GDS 路径 | `Optional[Path]` | 备份到 `state/backups/pre_update_{timestamp}.gds` |
| `GDSBackupManager.restore_backup(backup_path, target_path)` | 备份路径, 目标路径 | `bool` | 恢复备份 |

---

### 8. config — 配置文件

| 文件 | 用途 | 说明 |
|------|------|------|
| `config/mapping_rules.yaml` | 电气→几何映射规则 | 每种器件类型：查表、字段映射、默认值、约束 |
| `config/drc_rules/simple_rf.yaml` | DRC 规则 | spacing/width/area/not_empty 检查项 |

通过 `--pdk-config` 参数可指定用户自定义的映射规则文件，不传则使用默认配置。

---

## GDS 版图结构约定

PAM 对输入 GDS 有以下结构要求：

```
TOP (top cell)                         ← 连线画在这一层
  ├── C1_CAP_MIM (instance)            ← 器件实例
  │     └── [PIN marker 255/0 文本]    ← 引脚位置标记
  ├── L1_IND_SPIRAL (instance)
  │     └── [PIN marker 255/0 文本]
  └── TL1_TL_MICROSTRIP (instance)
        └── [PIN marker 255/0 文本]
```

**命名约定**：sub-cell 名 = `{位号}_{PCell名}`，如 `C1_CAP_MIM`、`L1_IND_SPIRAL`。

**层约定**（当前硬编码，后续将迁移到 PDK 配置）：

| 层号 | 用途 |
|------|------|
| 2/0 | 传输线地平面 |
| 6/0 | Metal1（传输线信号、电感底层走线） |
| 7/0 | Metal2（电感顶层走线） |
| 8/0 | 电容下极板 |
| 9/0 | MIM 介质层 |
| 9/1 | 电容 Via |
| 10/0 | 电容上极板 |
| 11/0 | 通孔层 |
| 100/0 | LVS 引脚标记（几何） |
| 200/0 | BROKEN 连线标记 |
| 255/0 | PIN marker（文本标签，引脚定位用） |

---

## 安装

```bash
git clone <repo-url>
cd pam-mvp-v5
pip install -e .
```

依赖：Python ≥ 3.10, KLayout (klayout.db Python 模块)。

---

## 示例

### 示例总览

| # | 示例 | 拓扑 | 器件数 | 变更器件 | 复杂度 |
|---|------|------|--------|----------|--------|
| 1 | L 匹配 | C + TL | 2 | 2 | 简单 |
| 2 | Pi 匹配 | C∥L∥C + TL | 4 | 4 | 中等 |
| 3 | T 匹配 | C + L + C + 2TL | 5 | 5 | 中等 |
| 4 | 级联 LC | TL-C-L-C-L-TL | 6 | 6 | 中等 |
| 5 | 双 Pi 级联 | 2×(C∥L∥C) + 3TL | 9 | 9 | 复杂 |
| 6 | 纯传输线 | TL + TL | 2 | 2 | 简单 |

---

### 1. L 匹配网络

最简单的示例：一个电容 + 一条传输线。

```bash
# 生成初始版图（仅首次）
python scripts/generate_initial_gds.py examples/l_match.net examples/l_match_initial.gds

# 第一次迭代：C1 1pF→2pF, TL1 1000um→2000um
pam run \
  --gds examples/l_match_initial.gds \
  --netlist examples/l_match.net \
  --modified-netlist examples/l_match_modified.net \
  --output examples/l_match_updated.gds

# 第二次迭代：C1 2pF→3pF
pam run \
  --gds examples/l_match_updated.gds \
  --netlist examples/l_match_modified.net \
  --modified-netlist examples/l_match_modified2.net \
  --output examples/l_match_updated_v2.gds
```

**文件说明：**
| 文件 | 内容 |
|------|------|
| `l_match.net` | C1: 1pF, TL1: 50Ohm/1000um |
| `l_match_modified.net` | C1: 2pF, TL1: 50Ohm/2000um |
| `l_match_modified2.net` | C1: 3pF, TL1: 50Ohm/2000um |

---

### 2. Pi 匹配网络

Pi 型拓扑：两个并联电容 + 一个串联电感 + 一条传输线。

```bash
# 生成初始版图
python scripts/generate_initial_gds.py examples/pi_match.net examples/pi_match_initial.gds

# 运行迭代：C1 1→2pF, L1 2→3nH, C2 1→3pF, TL1 1000→2000um
pam run \
  --gds examples/pi_match_initial.gds \
  --netlist examples/pi_match.net \
  --modified-netlist examples/pi_match_modified.net \
  --output examples/pi_match_updated.gds
```

**文件说明：**
| 文件 | 内容 |
|------|------|
| `pi_match.net` | C1: 1pF, L1: 2nH, C2: 1pF, TL1: 50Ohm/1000um |
| `pi_match_modified.net` | C1: 2pF, L1: 3nH, C2: 3pF, TL1: 50Ohm/2000um |

---

### 3. T 匹配网络

T 型拓扑：串联电感 + 两侧并联电容 + 输入输出传输线。

```bash
# 生成初始版图
python scripts/generate_initial_gds.py examples/t_match.net examples/t_match_initial.gds

# 运行迭代：C1 1→2pF, L1 2→3nH, C2 1→3pF, TL1 1000→2000um, TL2 1000→2000um
pam run \
  --gds examples/t_match_initial.gds \
  --netlist examples/t_match.net \
  --modified-netlist examples/t_match_modified.net \
  --output examples/t_match_updated.gds
```

**文件说明：**
| 文件 | 内容 |
|------|------|
| `t_match.net` | C1: 1pF, L1: 2nH, C2: 1pF, TL1: 50Ohm/1000um, TL2: 50Ohm/1000um |
| `t_match_modified.net` | C1: 2pF, L1: 3nH, C2: 3pF, TL1: 50Ohm/2000um, TL2: 50Ohm/2000um |

---

### 4. 级联 LC 网络

两条传输线之间级联两组 LC：TL1 → C1 → L1 → C2 → L2 → TL2。

```bash
# 生成初始版图
python scripts/generate_initial_gds.py examples/cascade_lc.net examples/cascade_lc_initial.gds

# 运行迭代：全部 6 个器件值变更
pam run \
  --gds examples/cascade_lc_initial.gds \
  --netlist examples/cascade_lc.net \
  --modified-netlist examples/cascade_lc_modified.net \
  --output examples/cascade_lc_updated.gds
```

**文件说明：**
| 文件 | 内容 |
|------|------|
| `cascade_lc.net` | TL1: 50Ohm/1000um, C1: 1pF, L1: 2nH, C2: 1pF, L2: 2nH, TL2: 72Ohm/2000um |
| `cascade_lc_modified.net` | TL1: 50Ohm/2000um, C1: 2pF, L1: 3nH, C2: 3pF, L2: 4nH, TL2: 72Ohm/1000um |

---

### 5. 双 Pi 级联网络

两个 Pi 网络通过传输线级联，9 个器件，4 个 junction 节点，最复杂的示例。

拓扑：TL1 → C1∥L1 → C2∥TL2 → C3∥L2 → C4∥TL3

```bash
# 生成初始版图
python scripts/generate_initial_gds.py examples/dual_pi.net examples/dual_pi_initial.gds

# 运行迭代：全部 9 个器件值变更
pam run \
  --gds examples/dual_pi_initial.gds \
  --netlist examples/dual_pi.net \
  --modified-netlist examples/dual_pi_modified.net \
  --output examples/dual_pi_updated.gds
```

**文件说明：**
| 文件 | 内容 |
|------|------|
| `dual_pi.net` | TL1: 50/500, C1: 1pF, L1: 2nH, C2: 1pF, TL2: 50/1000, C3: 1pF, L2: 2nH, C4: 1pF, TL3: 50/500 |
| `dual_pi_modified.net` | TL1: 50/800, C1: 1.5pF, L1: 3nH, C2: 1.5pF, TL2: 50/1500, C3: 2pF, L2: 3.5nH, C4: 2pF, TL3: 50/800 |

---

### 6. 纯传输线

最简示例：仅含两条传输线。

```bash
# 生成初始版图
python scripts/generate_initial_gds.py examples/tl_only.net examples/tl_only_initial.gds

# 运行迭代
pam run \
  --gds examples/tl_only_initial.gds \
  --netlist examples/tl_only.net \
  --modified-netlist examples/tl_only_modified.net \
  --output examples/tl_only_updated.gds
```

**文件说明：**
| 文件 | 内容 |
|------|------|
| `tl_only.net` | TL1: 50Ohm/1000um, TL2: 72Ohm/2000um |
| `tl_only_modified.net` | TL1: 50Ohm/500um, TL2: 72Ohm/1000um |

---

## 查看结果

生成的 GDS 文件使用 [KLayout](https://klayout.de/) 打开查看（建议 ≥ 0.28 版本）：

1. 打开 GDS 后选择 `TOP` cell
2. `Shift+F` 放大查看器件细节
3. 金属层走线在 Layer 6/0 (Metal1)
4. PIN marker 文本在 Layer 255/0

---

## 项目结构

```
pam-mvp-v5/
├── src/
│   ├── parser/          # 网表解析（KiCad S-expression + 差异比较）
│   │   ├── base.py      #   抽象基类 NetlistParser
│   │   ├── types.py     #   数据类 Component, Net
│   │   ├── factory.py   #   工厂路由 NetlistRouter
│   │   ├── kicad_netlist.py  # KiCad 解析器
│   │   ├── value_parser.py   # 器件值解析
│   │   ├── target_params.py  # 目标参数解析
│   │   ├── netlist_diff.py   # 网表差异比较
│   │   └── exceptions.py     # 异常定义
│   ├── mapper/          # 电气参数 → 几何参数映射
│   │   └── engine.py    #   MappingEngine 查表 + 约束
│   ├── routing/         # 布线（连线提取/擦除/重绘）
│   │   ├── types.py     #   PinState, WireSegment, Connection
│   │   ├── base.py      #   StretchRouter
│   │   ├── pin_extractor.py  # 引脚坐标提取
│   │   ├── wire_extractor.py # 连线提取/擦除
│   │   ├── wire_finder.py    # 连线发现
│   │   └── initial_router.py # 初始布线器
│   ├── core/            # 核心编排
│   │   ├── cli.py       #   命令行入口
│   │   └── runner.py    #   Runner 编排器
│   ├── validator/       # DRC / LVS 验证
│   │   ├── base.py      #   数据类 + 抽象基类
│   │   ├── drc_runner.py     # KLayout DRC
│   │   ├── ref_mapper.py     # 违例→器件映射
│   │   └── lvs_runner.py     # 纯 Python LVS
│   ├── executor/        # KLayout 执行器（兼容层）
│   └── state/           # 状态管理
│       └── snapshot_manager.py  # GDS 备份/恢复
├── pcells/              # 参数化单元
│   ├── base.py          #   BasePCell 抽象基类
│   ├── registry.py      #   @register 注册表
│   ├── mim_capacitor/   #   MIM 电容器 PCell
│   ├── spiral_inductor/ #   螺旋电感器 PCell
│   └── transmission_line/  # 微带传输线 PCell
├── config/              # 配置文件
│   ├── mapping_rules.yaml    # 电气→几何映射规则
│   └── drc_rules/
│       └── simple_rf.yaml    # RF DRC 规则
├── scripts/
│   └── generate_initial_gds.py  # 从网表生成初始版图
├── examples/            # 示例文件（网表 + GDS）
├── tests/               # 测试
└── docs/                # 文档
```

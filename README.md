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

## 输入依赖与要求

PAM 运行依赖三类输入：**网表文件**、**GDS 版图**、**PDK 配置**。以下详细说明每类输入的要求。

### 1. 网表文件要求

#### 格式

当前支持 KiCad S-expression 格式（`.net` 文件），由 KiCad 8.0 导出。文件扩展名需为 `.net` 或 `.sexp`。

#### 文件结构

```sexp
(export (version "E")
  (design
    (source "<原理图路径>")
    (date "<日期>")
    (tool "KiCad 8.0")
  )
  (components
    (comp (ref "<位号>")
      (value "<器件值>")
      (footprint "<封装>")
      (libsource (lib "<库名>") (part "<器件类型名>") (description "<描述>"))
    )
    ...
  )
  (nets
    (net (code <编号>) (name "<网络名>")
      (node (ref "<位号>") (pin "<引脚名>"))
      (node (ref "<位号>") (pin "<引脚名>"))
    )
    ...
  )
)
```

#### 字段说明

| 字段 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `ref` | 是 | 器件位号，全局唯一 | `"C1"`, `"TL1"`, `"L2"` |
| `value` | 是 | 器件值，格式与器件类型对应（见下表） | `"1pF"`, `"50Ohm/1000um"` |
| `part` | 是 | 器件类型名，必须与 `mapping_rules.yaml` 中的 key 对应 | `"CAP_MIM"`, `"IND_SPIRAL"`, `"TL_MICROSTRIP"` |
| `lib` | 否 | KiCad 库名 | `"RF"` |
| `footprint` | 否 | 封装名 | `"RF:MIM_Cap"` |
| `description` | 否 | 器件描述 | `"MIM Capacitor"` |

#### 器件值格式

不同器件类型的 `value` 字段格式不同，PAM 依赖此格式解析电气参数：

| 器件类型 (`part`) | value 格式 | 解析结果 | 示例 |
|-------------------|-----------|----------|------|
| `CAP_MIM` | `{数值}pF` | `{"capacitance_pf": 数值}` | `"1pF"` → `{"capacitance_pf": 1.0}` |
| `CAP_MIM` | `{数值}fF` | `{"capacitance_pf": 数值/1000}` | `"500fF"` → `{"capacitance_pf": 0.5}` |
| `IND_SPIRAL` | `{数值}nH` | `{"inductance_nH": 数值}` | `"2.5nH"` → `{"inductance_nH": 2.5}` |
| `TL_MICROSTRIP` | `{阻抗}Ohm/{长度}um` | `{"impedance_ohm": 阻抗, "length_um": 长度}` | `"50Ohm/1000um"` → `{"impedance_ohm": 50.0, "length_um": 1000.0}` |
| `TL_MICROSTRIP` | `{阻抗}Ohm_{长度}um` | 同上（`_` 代替 `/`） | `"50Ohm_2000um"` |

支持小数，如 `"1.5pF"`, `"3.5nH"`, `"72.5Ohm/1500um"`。

#### 引脚名约定

| 器件类型 | 引脚名 | 含义 |
|----------|--------|------|
| `CAP_MIM` | `PI` | 上极板（正端） |
| `CAP_MIM` | `NIN` | 下极板（负端，通常接地） |
| `IND_SPIRAL` | `PI` | 外端（起始端） |
| `IND_SPIRAL` | `NIN` | 底端（underpass 端） |
| `TL_MICROSTRIP` | `P1` | 输入端 |
| `TL_MICROSTRIP` | `P2` | 输出端 |

网表中的 `(node (ref "C1") (pin "PI"))` 中的引脚名必须与上表一致。

#### 网络连接规则

- 每个引脚只能属于一个网络（一个引脚不能出现在两个 `net` 中）
- 一个网络可以包含 2 个或更多节点（Pi/T 型 junction 节点有 3+ 节点）
- `RFIN` 和 `RFOUT` 为保留网络名，标识输入输出端口
- `GND` 为保留网络名，标识接地

#### 差异比较约束

`原始网表` 和 `修改后网表` 的差异比较规则：
- **支持**：已有器件的 `value` 值变更（如 `1pF` → `2pF`）
- **警告（不阻断）**：器件类型名变更（如 `CAP_MIM` → `CAP_MIM_V2`），此时跳过值比较
- **报错（阻断）**：器件增减（原始网表有而修改后没有，或反之）

---

### 2. GDS 版图要求

#### 版图层级结构

PAM 要求输入 GDS 遵循两级层级结构：

```
TOP (top cell)                              ← 连线画在 top cell 的金属层上
  ├── C1_CAP_MIM (instance)                 ← 第1层：器件实例
  │     ├── [上极板 Metal 10/0 几何]
  │     ├── [下极板 Metal 8/0 几何]
  │     ├── [MIM 介质 9/0 几何]
  │     ├── [Via 9/1 几何]
  │     └── [PIN marker 255/0 "PI"/"NIN" 文本]  ← 第2层：引脚标记
  ├── L1_IND_SPIRAL (instance)
  │     ├── [顶层走线 Metal 7/0]
  │     ├── [底层走线 Metal 6/0]
  │     ├── [Via 11/0]
  │     └── [PIN marker 255/0 "PI"/"NIN" 文本]
  └── TL1_TL_MICROSTRIP (instance)
        ├── [信号线 Metal 6/0]
        ├── [地平面 2/0]
        └── [PIN marker 255/0 "P1"/"P2" 文本]
```

#### 关键要求

| 要求 | 说明 | 不满足的后果 |
|------|------|-------------|
| **Cell 命名** | sub-cell 名必须为 `{位号}_{PCell名}` | PAM 无法通过位号匹配到对应 cell |
| **PIN marker 层** | 每个器件 sub-cell 必须在 `255/0` 层放置文本标签 | PAM 无法提取引脚坐标，布线失败 |
| **PIN marker 文本** | 文本内容必须与网表中引脚名一致（`PI`, `NIN`, `P1`, `P2`） | 引脚无法关联到网络 |
| **实例层级** | 器件实例必须是 top cell 的直接子实例 | 嵌套实例不会被扫描到 |
| **连线层级** | 金属连线必须画在 top cell 上（不在 sub-cell 内） | 连线提取失败或归属错误 |
| **器件几何** | 器件几何画在各自的 sub-cell 内 | 几何与连线混淆，提取错误 |

#### Sub-cell 命名约定

```
格式: {位号}_{PCell注册名}

示例:
  C1_CAP_MIM          → 位号 C1, MIM 电容
  L1_IND_SPIRAL       → 位号 L1, 螺旋电感
  TL1_TL_MICROSTRIP   → 位号 TL1, 微带传输线
  C10_CAP_MIM         → 位号 C10 (注意：C1 不会误匹配 C10)
```

命名规则：
- 位号与 PCell 名之间用 `_` 分隔
- PAM 通过检查分隔后第二部分首字符是否为字母来区分 `C1_CAP_MIM`（正确）和 `C10`（不会误匹配为 `C1` + `0`）
- 位号不能包含下划线

#### 层定义

PAM 使用以下 GDS 层号（当前硬编码，后续将迁移到 PDK 配置）：

| 层号/数据类型 | 物理含义 | 使用器件 | 说明 |
|-------------|---------|---------|------|
| `2/0` | 地平面 (GND) | TL_MICROSTRIP | 传输线下方接地金属 |
| `6/0` | Metal1 信号层 | TL_MICROSTRIP, IND_SPIRAL | 传输线信号、电感底层走线、top cell 连线 |
| `7/0` | Metal2 顶层 | IND_SPIRAL | 电感螺旋顶层走线 |
| `8/0` | 金属底层 (MB) | CAP_MIM | 电容下极板 |
| `9/0` | MIM 介质 | CAP_MIM | 电容介质层标识 |
| `9/1` | 电容 Via | CAP_MIM | 上下极板连接过孔 |
| `10/0` | 金属顶层 (MT) | CAP_MIM | 电容上极板 |
| `11/0` | 通孔 (Via) | IND_SPIRAL | 金属层间通孔 |
| `100/0` | LVS 引脚几何 | 所有器件 | LVS 检查时使用的引脚几何标记 |
| `200/0` | BROKEN 标记 | 连线 | 布线失败处的 X 标记 + "BROKEN:netname" 文本 |
| `255/0` | PIN marker | 所有器件 | 引脚位置文本标签，PAM 依赖此层提取引脚坐标 |

#### DRC 规则涉及的层

DRC 规则通过 `config/drc_rules/simple_rf.yaml` 配置，当前覆盖：

| 层 | 检查项 | 默认阈值 |
|----|--------|---------|
| `6/0` (Metal1) | min_spacing | 1.0 um |
| `6/0` (Metal1) | min_width | 2.0 um |
| `7/0` (Metal2) | min_spacing | 1.0 um |
| `7/0` (Metal2) | min_width | 3.0 um |
| `8/0` (MB) | min_spacing | 1.0 um |
| `9/0` (MIM) | min_area | 100 um² |
| `10/0` (MT) | min_spacing | 1.0 um |

#### 引脚坐标提取原理

PAM 从 GDS 中提取引脚坐标的过程：

1. 遍历 top cell 下所有 instance
2. 对每个 instance，读取其 sub-cell 中 `255/0` 层的文本标签
3. 标签文本即为引脚名（如 `"PI"`, `"NIN"`, `"P1"`, `"P2"`）
4. 通过 `instance.dcplx_trans` 将 sub-cell 局部坐标转换为全局坐标（考虑位移、旋转、镜像）
5. 返回 `{位号: {引脚名: (x_um, y_um)}}`

#### 连线提取原理

PAM 从 GDS top cell 中提取金属连线的过程：

1. 收集 top cell 上所有金属层 Shape（排除 `255/0` PIN marker 层）
2. 对每个 Shape 构造 BoundingBox
3. 查询哪些引脚落在 Box 内（通过引脚坐标判断）
4. 利用网表的 `pin → net` 映射将 Shape 归属到对应网络
5. 若 Shape 同时触及多个网络的引脚，发出警告并跳过该 Shape

---

### 3. PDK 配置要求

PDK 配置以 YAML 文件形式提供，通过 `--pdk-config` 参数指定。不传则使用默认的 `config/mapping_rules.yaml`。

#### mapping_rules.yaml 结构

```yaml
# 每种器件类型一个顶级 key
<device_type>:
  target_pcell: str           # PCell 注册名，必须与 pcells/registry.py 中 @register() 一致
  param_mapping: dict         # 查表字段名 → PCell 参数名的映射
  defaults: dict              # PCell 参数默认值（查表结果缺失时补充）
  constraints: dict           # 几何参数约束边界
  lookup_table: list[dict]    # 电气参数 → 几何参数 查找表
```

#### 各字段详解

**`target_pcell`**：指定该器件类型使用哪个 PCell 生成版图。

| device_type | target_pcell | 说明 |
|-------------|-------------|------|
| `capacitor_mim` | `CAP_MIM` | MIM 电容器 |
| `inductor_spiral` | `IND_SPIRAL` | 螺旋电感器 |
| `transmission_line` | `TL_MICROSTRIP` | 微带传输线 |

**`param_mapping`**：查表结果字段名到 PCell 参数名的重命名映射。查表返回的字段名可能与 PCell 接口参数名不同，通过此字段对齐。

```yaml
param_mapping:
  length_um: length    # 查表字段 "length_um" → PCell 参数 "length"
  # 同名字段可省略，如 length: length
```

**`defaults`**：PCell 参数默认值。查表结果中不包含的字段由此补充。

```yaml
defaults:
  spacing: 8.0         # 电感默认间距
  angle: 0.0           # 默认水平放置
```

**`constraints`**：几何参数的边界约束。PCell 生成前会校验参数是否在范围内。

```yaml
constraints:
  length: { min: 10, max: 200 }   # 长度 10~200 um
  width:  { min: 10, max: 200 }   # 宽度 10~200 um
```

- 约束缺失 → 该参数不校验，直接通过
- 参数越界 → 该器件更新被跳过（不阻断其他器件）
- 不在约束中的参数 → 不校验

**`lookup_table`**：电气参数到几何参数的查找表。PAM 使用欧氏距离在表中查找最近邻行。

```yaml
lookup_table:
  - { capacitance_pf: 0.5, length: 28,  width: 28  }
  - { capacitance_pf: 1.0, length: 40,  width: 40  }
  - { capacitance_pf: 2.0, length: 57,  width: 57  }
  - { capacitance_pf: 3.0, length: 70,  width: 70  }
  - { capacitance_pf: 5.0, length: 90,  width: 90  }
  - { capacitance_pf: 10.0, length: 127, width: 127 }
```

查找规则：
- 输入电气参数与表中每行计算欧氏距离
- 取距离最近的行作为映射结果
- 如果输入恰好不在表中（如 `1.5pF`），会匹配到最近行（`1pF` 或 `2pF`）
- 多维参数（如传输线的阻抗+长度）同时参与距离计算

#### drc_rules.yaml 结构

DRC 规则独立于映射规则，用于版图更新后的设计规则验证。

```yaml
rules:
  - name: str              # 规则名，如 "metal1.min_spacing"
    layer: "layer/datatype" # GDS 层号，如 "6/0"
    type: str               # 检查类型: spacing | width | area | not_empty
    value: float            # 阈值 (um 或 um²)
    severity: str           # 严重级别: error | warning
```

| 检查类型 | 含义 | value 单位 |
|---------|------|-----------|
| `spacing` | 同层图形最小间距 | um |
| `width` | 同层图形最小线宽 | um |
| `area` | 同层图形最小面积 | um² |
| `not_empty` | 该层不能为空 | — (value 被忽略) |

#### PDK 适配说明

当前 PAM 内置了一套示例 PDK 配置。实际使用时需要根据目标工艺替换：

| 需要适配的内容 | 配置位置 | 说明 |
|-------------|---------|------|
| 电气→几何映射表 | `mapping_rules.yaml` 的 `lookup_table` | 不同工艺相同电容值的版图尺寸不同 |
| 几何参数约束 | `mapping_rules.yaml` 的 `constraints` | 不同工艺的最小/最大尺寸限制不同 |
| DRC 规则阈值 | `drc_rules/*.yaml` | 不同工艺的间距/线宽/面积规则不同 |
| PCell 层号定义 | `pcells/*/pcell.py` (硬编码) | 不同工艺的金属层编号不同（后续将迁移到配置） |
| PCell 几何规则 | `pcells/*/pcell.py` | 不同工艺的器件结构可能不同 |

使用自定义 PDK 配置：
```bash
pam run \
  --pdk-config /path/to/my_pdk/mapping_rules.yaml \
  ...
```

---

### 4. 支持的器件类型

| 器件类型 | 网表 part 名 | 映射规则 key | PCell | 电气参数 | 几何参数 |
|---------|-------------|-------------|-------|---------|---------|
| MIM 电容 | `CAP_MIM` | `capacitor_mim` | `CAP_MIM` | `capacitance_pf` | `length`, `width` |
| 螺旋电感 | `IND_SPIRAL` | `inductor_spiral` | `IND_SPIRAL` | `inductance_nH` | `inner_radius`, `turns`, `width`, `spacing`, `angle` |
| 微带传输线 | `TL_MICROSTRIP` | `transmission_line` | `TL_MICROSTRIP` | `impedance_ohm`, `length_um` | `width`, `length`, `angle` |

网表 → 映射 → PCell 的对应链路：

```
网表 part 名 "CAP_MIM"
  → value_to_device_type() → "capacitor_mim"
  → mapping_rules.yaml key → target_pcell: "CAP_MIM"
  → pcells/registry.py → MIMCapacitor PCell
```

---

### 5. 软件依赖

| 依赖 | 版本要求 | 说明 |
|------|---------|------|
| Python | ≥ 3.10 | 使用 `match` 语法、`type` 联合语法 |
| KLayout | ≥ 0.28 | 提供 `klayout.db` Python 模块，用于 GDS 读写和几何操作 |
| PyYAML | — | 解析 PDK 配置和 DRC 规则 |
| sexpdata | — | KiCad S-expression 网表解析 |

安装：
```bash
git clone <repo-url>
cd pam-mvp-v5
pip install -e .
```

验证安装：
```bash
python -c "import klayout.db; print('KLayout OK')"
pam --help
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

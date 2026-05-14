# PAM 布局迭代自动化工具 使用指南

> 面向用户：软件小白 | 版本：0.1.0

---

## 目录

1. [什么是PAM？](#1-什么是pam)
2. [安装与环境配置](#2-安装与环境配置)
3. [核心概念快速理解](#3-核心概念快速理解)
4. [第一次使用：冷启动（init）](#4-第一次使用冷启动init)
5. [后续迭代：运行优化（run）](#5-后续迭代运行优化run)
6. [文件格式详解](#6-文件格式详解)
7. [常见问题与排查](#7-常见问题与排查)
8. [命令参考](#8-命令参考)

---

## 1. 什么是PAM？

PAM（Layout Iteration Automation Engine）是一个**版图迭代自动化工具**。

### 它能做什么？

想象你正在设计一个射频芯片，版图上有电容、电感、传输线等器件。每次优化电路参数后（比如把某个电容从2pF改成3pF），传统做法是手动在EDA软件里调整器件尺寸。PAM可以**自动完成这个过程**：

```
KiCad电路设计 → PAM自动映射 → 自动生成GDS版图 → 自动验证DRC/LVS
```

### 工作流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                        PAM 工作流程                               │
│                                                                 │
│   [KiCad网表]  ──→  [目标参数]  ──→  [映射引擎]  ──→  [GDS]     │
│        │                │              │               │        │
│        ▼                ▼              ▼               ▼        │
│   定义器件连接      告诉PAM你想要   查表找到对应的   输出的      │
│   关系和网络        每个器件的参数   几何尺寸         版图文件   │
│                                                                 │
│   第一次运行: pam init（冷启动）                                  │
│   后续迭代:   pam run（自动优化）                                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 安装与环境配置

### 2.1 环境要求

- **Python**: 3.10 或更高版本
- **KLayout**: 0.28 或更高版本（用于查看和处理GDS文件）
- **操作系统**: Linux（本工具在Linux环境下开发）

### 2.2 安装步骤

```bash
# 1. 进入项目目录
cd /root/pam/pam-mvp-v5

# 2. 安装依赖
pip install -e ".[dev]"

# 3. 验证安装成功
pam --help
```

如果看到类似下面的输出，说明安装成功：

```
usage: PAM Layout Iteration Automation Engine
subcommands:
  init   生成初版GDS和参数快照（冷启动）
  run    执行版图迭代优化
```

### 2.3 KLayout安装

KLayout是查看GDS文件的工具。

```bash
# Ubuntu/Debian
sudo apt-get install klayout

# 或从官网下载：https://www.klayout.de/
```

---

## 3. 核心概念快速理解

### 3.1 什么是网表（Netlist）？

网表是电路设计的"连接图"，它告诉计算机：
- 有哪些器件（如C1电容、TL1传输线）
- 这些器件怎么连接的（通过哪些网络）

KiCad导出的网表示例（`l_match.net`）：

```
(export (version "E")
  (components
    (comp (ref "C1") (value "1pF") ...)
    (comp (ref "TL1") (value "50Ohm/1000um") ...)
  )
  (nets
    (net (code 1) (name "RFIN")
      (node (ref "TL1") (pin "P1") ...)
    )
    ...
  )
)
```

### 3.2 什么是目标参数（Target Params）？

目标参数是你**想要的电气性能**，比如：
- 电容：2pF（不是具体尺寸，而是电气值）
- 电感：2nH
- 传输线：50欧姆阻抗、2000微米长度

PAM会自动把这些电气值转换成实际的器件尺寸。

### 3.3 什么是PCell？

PCell = Parameterized Cell（参数化单元）。每个PCell代表一种器件类型：

| PCell类型 | 对应器件 | 关键参数 |
|-----------|----------|----------|
| CAP_MIM | MIM电容 | length, width |
| IND_SPIRAL | 螺旋电感 | inner_radius, turns, width, spacing |
| TL_MICROSTRIP | 微带传输线 | width, length, angle |

### 3.4 什么是GDS？

GDS是版图的标准格式，可以被所有EDA工具读取。可以理解为"版图的矢量图文件"。

### 3.5 什么是DRC和LVS？

- **DRC**（Design Rule Check）：检查版图是否符合制造规则（比如线宽是否太细、线间距是否够）
- **LVS**（Layout vs Schematic）：检查版图和电路原理图是否一致（器件连接关系是否正确）

---

## 4. 第一次使用：冷启动（init）

### 4.1 使用场景

当你有了一个新的电路设计，需要**第一次生成版图**时使用。

### 4.2 完整示例

假设我们有一个电路，包含：
- 一个2pF的MIM电容
- 一个2nH的螺旋电感
- 一根50欧姆、2000微米长的传输线

**Step 1: 准备KiCad网表**

确保你有KiCad导出的网表文件（`.net`格式）。本工具使用KiCad 8.0格式。

**Step 2: 准备目标参数文件**

创建 `my_target_params.json`：

```json
[
  {
    "reference": "C1",
    "type": "capacitor_mim",
    "params": {
      "capacitance_pf": 2.0
    }
  },
  {
    "reference": "L1",
    "type": "inductor_spiral",
    "params": {
      "inductance_nH": 2.0
    }
  },
  {
    "reference": "TL1",
    "type": "transmission_line",
    "params": {
      "impedance_ohm": 50,
      "length_um": 2000
    }
  }
]
```

**Step 3: 运行init命令**

```bash
pam init \
  --netlist my_circuit.net \
  --params my_target_params.json \
  --output first_layout.gds \
  --state-dir ./state
```

**Step 4: 查看输出**

命令成功后，你会看到：

```
[PAM Init 完成]
  初版GDS: first_layout.gds
  参数快照: state/params_snapshot.json

后续迭代命令:
  pam run --gds first_layout.gds --netlist my_circuit.net \
    --target <new_params.json> --output <updated.gds>

参数快照记录了所有器件的当前params和pins，
下次迭代时StretchRouter将据此执行实际连线拉伸。
```

### 4.3 init命令生成了什么？

1. **GDS文件** (`first_layout.gds`)：初版版图，可用KLayout打开查看
2. **参数快照** (`state/params_snapshot.json`)：记录所有器件的当前参数和引脚位置

---

## 5. 后续迭代：运行优化（run）

### 5.1 使用场景

当你修改了电路参数（比如把2pF电容改成3pF），需要**更新版图**时使用。

### 5.2 完整示例

**Step 1: 修改目标参数**

创建新的参数文件 `new_target_params.json`：

```json
[
  {
    "reference": "C1",
    "type": "capacitor_mim",
    "params": {
      "capacitance_pf": 3.0
    }
  },
  {
    "reference": "L1",
    "type": "inductor_spiral",
    "params": {
      "inductance_nH": 2.5
    }
  },
  {
    "reference": "TL1",
    "type": "transmission_line",
    "params": {
      "impedance_ohm": 50,
      "length_um": 3000
    }
  }
]
```

**Step 2: 运行run命令**

```bash
pam run \
  --gds first_layout.gds \
  --netlist my_circuit.net \
  --target new_target_params.json \
  --output updated_layout.gds \
  --state-dir ./state
```

**Step 3: 查看输出**

成功时：

```
SUCCESS: 版图更新完成 → updated_layout.gds
  更新器件: ['C1', 'L1', 'TL1']
  连线: 拉伸 2 条, 断线 0 条
  耗时: 0.35s
```

---

## 6. 文件格式详解

### 6.1 网表格式（KiCad导出）

KiCad网表是S-expression格式，结构如下：

```
(export (version "E")
  (design
    (source "...")      ; 设计源文件路径
    (date "...")        ; 导出日期
    (tool "KiCad 8.0") ; 工具版本
  )
  (components
    (comp (ref "C1")    ; 器件引用名（如C1, L1, TL1）
      (value "1pF")     ; 器件值
      (footprint "...") ; 封装
      (libsource ...)   ; 器件库信息
    )
    ...更多器件...
  )
  (nets
    (net (code 1) (name "RFIN")   ; 网络编号和名称
      (node (ref "TL1") (pin "P1") (pin_function "passive"))
    )
    ...更多网络...
  )
)
```

### 6.2 目标参数格式（JSON）

```json
[
  {
    "reference": "C1",           // 必须与网表中的ref一致
    "type": "capacitor_mim",    // 器件类型
    "params": {
      "capacitance_pf": 2.0    // 电气参数值
    }
  }
]
```

**支持的器件类型和参数：**

| type值 | 电气参数 | 说明 |
|--------|----------|------|
| `capacitor_mim` | `capacitance_pf` | 电容值，单位pF |
| `inductor_spiral` | `inductance_nH` | 电感值，单位nH |
| `transmission_line` | `impedance_ohm`, `length_um` | 阻抗(欧姆)和长度(微米) |

### 6.3 映射规则（config/mapping_rules.yaml）

这个文件定义了**电气值如何转换成物理尺寸**。

以MIM电容为例：

```yaml
capacitor_mim:
  target_pcell: "CAP_MIM"      # 目标PCell类型
  constraints:                  # 尺寸约束（微米）
    length: { min: 10, max: 200 }
    width:  { min: 10, max: 200 }
  lookup_table:                 # 查表：电气值 → 物理尺寸
    - { capacitance_pf: 0.5,  length: 28,  width: 28 }
    - { capacitance_pf: 1.0,  length: 40,  width: 40 }
    - { capacitance_pf: 2.0,  length: 57,  width: 57 }
    - { capacitance_pf: 3.0,  length: 70,  width: 70 }
```

### 6.4 状态快照（state/*.json）

每次迭代后，PAM会保存状态快照，包含：

```json
{
  "gds_path": "output.gds",       // GDS文件路径
  "timestamp": "2026-05-14T10:30:00",
  "devices": {
    "C1": {
      "ref": "C1",
      "pcell_type": "CAP_MIM",
      "params": {"length": 57, "width": 57},
      "pins": {
        "PI": {"name": "PI", "x": 57.0, "y": 28.5},
        "NIN": {"name": "NIN", "x": 57.0, "y": 4.5}
      }
    }
  }
}
```

---

## 7. 常见问题与排查

### 7.1 安装问题

**Q: `pam: command not found`**
```
# 重新安装
pip install -e .

# 或使用Python模块方式
python -m core.cli --help
```

**Q: `ModuleNotFoundError: No module named 'klayout.db'`**
```
# 安装KLayout Python API
# Ubuntu/Debian:
sudo apt-get install python3-klayout

# 或从源码编译KLayout
```

### 7.2 运行问题

**Q: `网表解析失败`**
- 检查网表文件是否存在
- 确认是KiCad 8.0格式（不是旧版本）
- 确认文件是文本格式，不是二进制

**Q: `无映射规则: device_type=xxx`**
- 检查目标参数中的`type`字段是否正确
- 确认在`config/mapping_rules.yaml`中有对应的映射规则

**Q: `查表无匹配`**
- 电气参数值超出映射表范围
- 检查参数名是否正确（如`capacitance_pf`不是`capacitance`）

**Q: `GDS文件中的器件引用不存在`**
- 网表中的器件ref必须与GDS中的cell名称匹配
- 检查大小写是否一致

### 7.3 DRC/LVS问题

**Q: DRC检查失败**
- 版图不符合制造规则
- 打开生成的GDS文件，在KLayout中运行DRC查看具体错误

**Q: LVS不匹配**
- 器件连接关系与网表不一致
- 检查引脚位置是否正确
- 可能需要手动调整器件位置

### 7.4 调试方法

**启用详细日志：**
```bash
pam run --gds input.gds --netlist circuit.net \
  --target params.json --output out.gds -v
```

**查看中间状态：**
```bash
# 查看参数快照
cat state/params_snapshot.json | python -m json.tool

# 查看历史记录
cat state/history.jsonl
```

---

## 8. 命令参考

### 8.1 pam init（冷启动）

```bash
pam init [选项]

必选选项：
  --netlist FILE      KiCad网表文件路径
  --params FILE       目标参数JSON文件路径
  --output FILE       输出GDS文件路径

可选选项：
  --rules FILE        映射规则YAML路径（默认：config/mapping_rules.yaml）
  --state-dir DIR     状态目录（默认：state）
```

**示例：**
```bash
pam init \
  --netlist my_circuit.net \
  --params initial_params.json \
  --output layout.gds
```

### 8.2 pam run（迭代优化）

```bash
pam run [选项]

必选选项：
  --gds FILE          输入GDS文件路径
  --netlist FILE      KiCad网表文件路径
  --target FILE       目标参数JSON文件路径

可选选项：
  --output FILE       输出GDS文件路径（默认：output.gds）
  --rules FILE        映射规则YAML路径（默认：config/mapping_rules.yaml）
  --state-dir DIR     状态目录（默认：state）
  --history FILE      历史记录文件（默认：state/history.jsonl）
  -v, --verbose       详细日志输出
```

**示例：**
```bash
pam run \
  --gds layout.gds \
  --netlist my_circuit.net \
  --target new_params.json \
  --output updated_layout.gds \
  -v
```

---

## 附录：完整示例

### A. 创建最小示例

```bash
# 1. 创建工作目录
mkdir my_project && cd my_project

# 2. 创建KiCad网表文件（my_circuit.net）
# 3. 创建目标参数文件（params.json）
# 4. 运行冷启动
pam init --netlist my_circuit.net --params params.json --output layout.gds

# 5. 修改参数并迭代
# （修改params.json内容）
pam run --gds layout.gds --netlist my_circuit.net --target params.json --output layout_v2.gds

# 6. 查看结果
klayout layout_v2.gds  # 用KLayout打开查看
```

### B. 批量迭代脚本示例

```bash
#!/bin/bash
# iterate.sh - 批量迭代脚本

GDS="layout.gds"
NETLIST="my_circuit.net"
STATE_DIR="./state"

for i in 1 2 3 4 5; do
  TARGET="params_iter${i}.json"
  OUTPUT="layout_iter${i}.gds"

  echo "=== Iteration $i ==="
  pam run \
    --gds "$GDS" \
    --netlist "$NETLIST" \
    --target "$TARGET" \
    --output "$OUTPUT" \
    --state-dir "$STATE_DIR"

  if [ $? -ne 0 ]; then
    echo "Iteration $i failed!"
    exit 1
  fi

  # 将输出作为下次输入
  GDS="$OUTPUT"
done

echo "All iterations completed!"
```

---

## 更新日志

| 版本 | 日期 | 说明 |
|------|------|------|
| 0.1.0 | 2026-05-14 | 初始版本 |

---

*本指南最后更新于 2026-05-14*

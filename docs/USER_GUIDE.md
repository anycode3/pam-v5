# PAM 操作手册

## 1. 概述

PAM（Parameterized Auto-layout Manager）是一个 RF 无源电路版图迭代自动化工具。

**核心能力**：当你修改了电路的器件参数（如把电容从 1pF 改为 2pF），PAM 能自动：
- 识别哪些器件发生了变化
- 重新生成变化器件的版图几何
- 擦除旧连线、重新布线
- 执行 DRC/LVS 验证

**每次 `run` 完全独立**，无需预先初始化，不依赖快照文件，所有信息直接从 GDS 版图实时提取。

---

## 2. 安装

### 2.1 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | ≥ 3.10 | 运行环境 |
| klayout | ≥ 0.28 | GDS 读写、PCell API |
| sexpdata | ≥ 1.0 | 解析 KiCad 网表 |
| PyYAML | ≥ 6.0 | 读取映射规则 |

### 2.2 安装步骤

```bash
git clone https://github.com/anycode3/pam-v5.git
cd pam-v5
pip install .
```

验证安装：
```bash
pam run --help
```

---

## 3. 快速开始

项目自带示例文件，可以立即体验：

```bash
# 基本用法：修改电容值 1pF → 2pF，传输线长度 1000um → 2000um
pam run \
  --gds examples/l_match_initial.gds \
  --netlist examples/l_match.net \
  --modified-netlist examples/l_match_modified.net \
  --output examples/updated_layout.gds
```

成功输出：
```
SUCCESS: 版图更新完成 → examples/updated_layout.gds
  变更: C1 '1pF' → '2pF'
  变更: TL1 '50Ohm/1000um' → '50Ohm/2000um'
  更新器件: ['C1', 'TL1']
  耗时: 0.35s
```

---

## 4. 命令参考

### `pam run`

PAM 只有一个命令 `run`，执行版图迭代更新。

```
pam run --gds GDS --netlist NETLIST --modified-netlist MOD_NETLIST [选项]
```

#### 必需参数

| 参数 | 说明 |
|------|------|
| `--gds` | 输入 GDS 版图文件路径 |
| `--netlist` | 原始 KiCad 网表文件路径 |
| `--modified-netlist` | 修改后的 KiCad 网表文件路径 |

#### 可选参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--rules` | `config/mapping_rules.yaml` | 映射规则 YAML 路径 |
| `--output` | `output.gds` | 输出 GDS 文件路径 |
| `--state-dir` | `state` | 状态目录（备份文件存放位置） |
| `--history` | `state/history.jsonl` | 操作历史文件路径 |
| `--no-drc` | 关 | 跳过 DRC 验证 |
| `--lvs` | 关 | 启用 LVS 验证 |
| `--verbose` / `-v` | 关 | 详细日志输出 |

---

## 5. 工作流程

```
┌─────────────────────────────────────────────────────────┐
│                     pam run                              │
│                                                         │
│  1. 解析原始网表 ──────────── 解析修改后网表              │
│              │                          │               │
│  2. Diff 找出值变化的器件 ←────────────┘               │
│              │                                          │
│  3. 映射：新 value → 电气参数 → 几何参数                │
│              │                                          │
│  4. 从 GDS 提取旧引脚坐标和旧连线                       │
│              │                                          │
│  5. 替换器件（重新生成 PCell 几何）                     │
│              │                                          │
│  6. 擦除旧连线 + 根据新引脚位置重新布线                  │
│              │                                          │
│  7. DRC 验证（含自动重试）                              │
│              │                                          │
│  8. LVS 验证（可选）                                    │
│              │                                          │
│  9. 记录历史 → 输出 GDS                                 │
└─────────────────────────────────────────────────────────┘
```

### 5.1 网表差异检测

PAM 对比原始网表和修改后网表，检测以下情况：

| 变化类型 | 处理方式 |
|----------|----------|
| 器件值变化（如 `1pF` → `2pF`） | 正常处理，更新版图 |
| 器件类型变化（如 `CAP_MIM` → `IND_SPIRAL`） | 报错，暂不支持 |
| 新增器件 | 报错，暂不支持 |
| 删除器件 | 报错，暂不支持 |
| 无变化 | 直接返回，不修改版图 |

### 5.2 值字符串格式

PAM 识别 KiCad 网表中的值字符串：

| 器件类型 | 值格式 | 示例 |
|----------|--------|------|
| CAP_MIM | `XpF` 或 `XfF` | `1pF`, `2.5pF`, `500fF` |
| IND_SPIRAL | `XnH` | `1nH`, `2.5nH` |
| TL_MICROSTRIP | `XOhm/Yum` 或 `XOhm_Yum` | `50Ohm/1000um`, `50Ohm_2000um` |

### 5.3 映射规则

值字符串先解析为电气参数，再通过 `mapping_rules.yaml` 查表映射为几何参数：

```
"2pF" → {capacitance_pf: 2.0} → 查表 → {length: 57, width: 57}
```

映射规则定义在 `config/mapping_rules.yaml`，可以自定义扩展。

### 5.4 连线重建

当器件参数变化导致引脚位置改变时，PAM 会：

1. 从 GDS 版图提取旧连线（top cell 上的金属层形状）
2. 识别受影响网络的旧连线
3. 擦除旧连线
4. 根据新引脚位置重新布线（直连或 L 型折线）

### 5.5 DRC 自动重试

DRC 验证失败时，PAM 会自动尝试修正：

1. 回滚到备份 GDS
2. 将违例器件的几何参数缩小 0.9 倍
3. 重新生成版图
4. 重新检查 DRC

最多重试 3 次。如果所有重试都失败，输出回滚后的 GDS。

---

## 6. 输入文件格式

### 6.1 KiCad 网表

PAM 接受 KiCad 导出的 S-expression 格式网表：

```lisp
(export (version "E")
  (components
    (comp (ref "C1")
      (value "1pF")
      (libsource (lib "RF") (part "CAP_MIM"))
    )
    (comp (ref "TL1")
      (value "50Ohm/1000um")
      (libsource (lib "RF") (part "TL_MICROSTRIP"))
    )
  )
  (nets
    (net (code 1) (name "NET_C1_TL1")
      (node (ref "C1") (pin "PI"))
      (node (ref "TL1") (pin "P2"))
    )
  )
)
```

**关键字段**：
- `ref`：器件引用名，必须与 GDS 中的子 cell 名前缀一致（如 `C1` 匹配 `C1_CAP_MIM`）
- `value`：器件参数值，必须遵循上述格式规范
- `part`（libsource 中）：器件类型，必须是 `CAP_MIM`、`IND_SPIRAL` 或 `TL_MICROSTRIP`
- `nets`：网络连接关系，决定布线

### 6.2 GDS 版图

输入 GDS 需要满足以下结构：

```
TOP (top cell)           ← 连线画在这里
  ├── C1_CAP_MIM (inst)  ← 器件子 cell
  ├── L1_IND_SPIRAL (inst)
  └── TL1_TL_MICROSTRIP (inst)
```

**命名规则**：子 cell 名必须是 `{ref}_{PCell类型}` 格式，如 `C1_CAP_MIM`。

**PIN Marker**：子 cell 内部在 (255/0) 层放置文本标记引脚位置，文本内容为引脚名（如 `PI`、`NIN`）。

### 6.3 映射规则 YAML

映射规则文件 `config/mapping_rules.yaml` 定义电气参数到几何参数的查表关系。支持三种器件类型，每种包含：

- `target_pcell`：对应的 PCell 注册名
- `param_mapping`：查表字段 → PCell 参数名的映射
- `defaults`：默认参数值
- `constraints`：参数约束范围
- `lookup_table`：电气值 → 几何值的查找表

详见 `config/mapping_rules.yaml` 中的注释。

---

## 7. 输出文件

### 7.1 GDS 版图

`--output` 指定的输出文件，包含更新后的版图。

### 7.2 操作历史

`state/history.jsonl` 记录每次运行的详细信息：

```json
{
  "timestamp": "2026-05-15T14:30:00",
  "action": "layout_update",
  "changes": [
    {"reference": "C1", "old_value": "1pF", "new_value": "2pF"}
  ],
  "mapped": [
    {"reference": "C1", "pcell": "CAP_MIM", "geometry": {"length": 57, "width": 57}}
  ],
  "result": "success",
  "drc": {"enabled": true, "passed": true, "violations": 0, "retries": 0}
}
```

### 7.3 GDS 备份

运行前自动保存输入 GDS 的备份到 `state/backups/`，用于 DRC/LVS 失败时回滚。

---

## 8. 支持的器件

| PCell | 类型 | 参数 | 值格式 |
|-------|------|------|--------|
| CAP_MIM | MIM 电容 | length, width | `XpF` / `XfF` |
| IND_SPIRAL | 螺旋电感 | inner_radius, turns, width, spacing, angle | `XnH` |
| TL_MICROSTRIP | 微带传输线 | width, length, angle | `XOhm/Yum` |

### 电容查表（CAP_MIM）

| 电容值 | length (um) | width (um) |
|--------|-------------|------------|
| 0.5 pF | 28 | 28 |
| 1.0 pF | 40 | 40 |
| 2.0 pF | 57 | 57 |
| 3.0 pF | 70 | 70 |
| 5.0 pF | 90 | 90 |
| 10.0 pF | 127 | 127 |

### 电感查表（IND_SPIRAL）

| 电感值 | inner_radius (um) | turns | width (um) |
|--------|-------------------|-------|------------|
| 0.5 nH | 30 | 1.5 | 10 |
| 1.0 nH | 35 | 2.0 | 10 |
| 2.0 nH | 50 | 3.0 | 10 |
| 3.0 nH | 55 | 4.0 | 10 |
| 5.0 nH | 65 | 5.0 | 10 |

### 传输线查表（TL_MICROSTRIP）

| 阻抗 (Ohm) | 长度 (um) | width (um) |
|-------------|-----------|------------|
| 25 | 1000 | 50 |
| 25 | 2000 | 50 |
| 50 | 500 | 20 |
| 50 | 1000 | 20 |
| 50 | 2000 | 20 |
| 50 | 3000 | 20 |
| 72 | 1000 | 10 |
| 72 | 2000 | 10 |

---

## 9. 常见问题

### Q: `pam: command not found`

重新安装：
```bash
pip install . --force-reinstall
```

### Q: `ModuleNotFoundError: No module named 'klayout'`

```bash
pip install klayout
```

### Q: GDS 中找不到器件

确保子 cell 命名遵循 `{ref}_{PCell类型}` 格式。例如引用名为 `C1` 的 MIM 电容，cell 名必须是 `C1_CAP_MIM`。

### Q: 值字符串解析失败

检查值格式是否符合规范。支持的格式：`1pF`、`2.5nH`、`50Ohm/1000um`。注意空格可选，大小写不敏感。

### Q: 映射失败，"无法找到匹配的几何参数"

mapping_rules.yaml 的查表中没有对应的电气值。需要在 YAML 中添加对应的查找表条目。

### Q: DRC 始终失败

检查 `config/drc_rules/simple_rf.yaml` 中的规则是否与工艺匹配。可以用 `--no-drc` 跳过 DRC 检查。

### Q: 修改后网表增加了新器件

PAM 目前不支持器件增减，只支持修改已有器件的值。如需增加器件，请先在 GDS 中手动添加对应的子 cell。

---

## 10. 目录结构

```
pam-v5/
├── config/
│   ├── mapping_rules.yaml       # 电气值→几何参数映射规则
│   └── drc_rules/
│       └── simple_rf.yaml       # DRC 规则
├── examples/
│   ├── l_match.net              # L 匹配原始网表
│   ├── l_match_modified.net     # 修改后网表（示例1）
│   ├── l_match_modified2.net    # 修改后网表（示例2）
│   └── ...                      # 更多示例见下方
├── src/
│   ├── core/
│   │   ├── cli.py               # CLI 入口
│   │   └── runner.py            # 核心调度器
│   ├── parser/
│   │   ├── kicad_netlist.py     # KiCad 网表解析器
│   │   ├── netlist_diff.py      # 网表差异比较
│   │   └── value_parser.py      # 值字符串解析
│   ├── mapper/
│   │   └── engine.py            # 映射引擎
│   ├── routing/
│   │   ├── initial_router.py    # 布线器
│   │   ├── pin_extractor.py     # 引脚坐标提取
│   │   ├── wire_extractor.py    # 连线提取/擦除
│   │   └── types.py             # 数据类型
│   ├── validator/
│   │   ├── drc_runner.py        # DRC 验证
│   │   └── lvs_runner.py        # LVS 验证
│   └── executor/
│       └── klayout_executor.py  # KLayout 执行器（兼容）
├── pcells/
│   ├── mim_capacitor/           # MIM 电容 PCell
│   ├── spiral_inductor/         # 螺旋电感 PCell
│   ├── transmission_line/       # 传输线 PCell
│   └── registry.py              # PCell 注册表
├── state/
│   ├── snapshot_manager.py      # GDS 备份管理
│   └── backups/                 # GDS 备份文件
├── tests/                       # 单元测试
└── docs/                        # 文档
```

# PAM 示例

本目录包含 6 个可运行的示例，从简单到复杂覆盖常见 RF 无源电路拓扑。

## 快速上手

```bash
# 1. 从网表生成初始版图（首次需要）
python scripts/generate_initial_gds.py examples/l_match.net examples/l_match_initial.gds

# 2. 运行版图迭代
pam run \
  --gds examples/l_match_initial.gds \
  --netlist examples/l_match.net \
  --modified-netlist examples/l_match_modified.net \
  --output examples/l_match_updated.gds
```

---

## 示例列表

| # | 示例 | 拓扑 | 器件数 | 变更器件 | 复杂度 |
|---|------|------|--------|----------|--------|
| 1 | L 匹配 | C + TL | 2 | 2 | 简单 |
| 2 | Pi 匹配 | C∥L∥C + TL | 4 | 4 | 中等 |
| 3 | T 匹配 | C + L + C + 2TL | 5 | 5 | 中等 |
| 4 | 级联 LC | TL-C-L-C-L-TL | 6 | 6 | 中等 |
| 5 | 双 Pi 级联 | 2×(C∥L∥C) + 3TL | 9 | 9 | 复杂 |
| 6 | 纯传输线 | TL + TL | 2 | 2 | 简单 |

---

### 1. L 匹配网络 (`l_match`)

C1 + TL1

```bash
python scripts/generate_initial_gds.py examples/l_match.net examples/l_match_initial.gds

pam run \
  --gds examples/l_match_initial.gds \
  --netlist examples/l_match.net \
  --modified-netlist examples/l_match_modified.net \
  --output examples/l_match_updated.gds
```

| 文件 | 内容 |
|------|------|
| `l_match.net` | C1: 1pF, TL1: 50Ohm/1000um |
| `l_match_modified.net` | C1: 2pF, TL1: 50Ohm/2000um |
| `l_match_modified2.net` | C1: 3pF, TL1: 50Ohm/2000um |

---

### 2. Pi 匹配网络 (`pi_match`)

C1(并联) + L1(串联) + C2(并联) + TL1

```bash
python scripts/generate_initial_gds.py examples/pi_match.net examples/pi_match_initial.gds

pam run \
  --gds examples/pi_match_initial.gds \
  --netlist examples/pi_match.net \
  --modified-netlist examples/pi_match_modified.net \
  --output examples/pi_match_updated.gds
```

| 文件 | 内容 |
|------|------|
| `pi_match.net` | C1: 1pF, L1: 2nH, C2: 1pF, TL1: 50Ohm/1000um |
| `pi_match_modified.net` | C1: 2pF, L1: 3nH, C2: 3pF, TL1: 50Ohm/2000um |

---

### 3. T 匹配网络 (`t_match`)

C1(并联) + L1(串联) + C2(并联) + TL1 + TL2

```bash
python scripts/generate_initial_gds.py examples/t_match.net examples/t_match_initial.gds

pam run \
  --gds examples/t_match_initial.gds \
  --netlist examples/t_match.net \
  --modified-netlist examples/t_match_modified.net \
  --output examples/t_match_updated.gds
```

| 文件 | 内容 |
|------|------|
| `t_match.net` | C1: 1pF, L1: 2nH, C2: 1pF, TL1: 50Ohm/1000um, TL2: 50Ohm/1000um |
| `t_match_modified.net` | C1: 2pF, L1: 3nH, C2: 3pF, TL1: 50Ohm/2000um, TL2: 50Ohm/2000um |

---

### 4. 级联 LC 网络 (`cascade_lc`)

TL1 → C1 → L1 → C2 → L2 → TL2

```bash
python scripts/generate_initial_gds.py examples/cascade_lc.net examples/cascade_lc_initial.gds

pam run \
  --gds examples/cascade_lc_initial.gds \
  --netlist examples/cascade_lc.net \
  --modified-netlist examples/cascade_lc_modified.net \
  --output examples/cascade_lc_updated.gds
```

| 文件 | 内容 |
|------|------|
| `cascade_lc.net` | TL1: 50Ohm/1000um, C1: 1pF, L1: 2nH, C2: 1pF, L2: 2nH, TL2: 72Ohm/2000um |
| `cascade_lc_modified.net` | TL1: 50Ohm/2000um, C1: 2pF, L1: 3nH, C2: 3pF, L2: 4nH, TL2: 72Ohm/1000um |

---

### 5. 双 Pi 级联网络 (`dual_pi`)

TL1 → C1∥L1 → C2∥TL2 → C3∥L2 → C4∥TL3（9 器件，4 个 junction 节点）

```bash
python scripts/generate_initial_gds.py examples/dual_pi.net examples/dual_pi_initial.gds

pam run \
  --gds examples/dual_pi_initial.gds \
  --netlist examples/dual_pi.net \
  --modified-netlist examples/dual_pi_modified.net \
  --output examples/dual_pi_updated.gds
```

| 文件 | 内容 |
|------|------|
| `dual_pi.net` | TL1: 50/500, C1: 1pF, L1: 2nH, C2: 1pF, TL2: 50/1000, C3: 1pF, L2: 2nH, C4: 1pF, TL3: 50/500 |
| `dual_pi_modified.net` | TL1: 50/800, C1: 1.5pF, L1: 3nH, C2: 1.5pF, TL2: 50/1500, C3: 2pF, L2: 3.5nH, C4: 2pF, TL3: 50/800 |

---

### 6. 纯传输线 (`tl_only`)

TL1 + TL2

```bash
python scripts/generate_initial_gds.py examples/tl_only.net examples/tl_only_initial.gds

pam run \
  --gds examples/tl_only_initial.gds \
  --netlist examples/tl_only.net \
  --modified-netlist examples/tl_only_modified.net \
  --output examples/tl_only_updated.gds
```

| 文件 | 内容 |
|------|------|
| `tl_only.net` | TL1: 50Ohm/1000um, TL2: 72Ohm/2000um |
| `tl_only_modified.net` | TL1: 50Ohm/500um, TL2: 72Ohm/1000um |

---

## CLI 参数

```
pam run \
  --gds <GDS路径>                 # 必填：当前版图文件
  --netlist <原始网表>             # 必填：与当前版图对应的网表
  --modified-netlist <新网表>      # 必填：修改后的网表
  --pdk-config <YAML路径>          # 可选：PDK配置（默认 config/mapping_rules.yaml）
  --output <输出路径>              # 可选：输出 GDS（默认 output.gds）
  --no-drc                        # 可选：跳过 DRC 检查
  --lvs                           # 可选：启用 LVS 验证
  -v                              # 可选：详细日志
```

## 查看结果

使用 [KLayout](https://klayout.de/)（≥ 0.28）打开 GDS：
1. 选择 `TOP` cell 显示
2. `Shift+F` 放大查看器件细节
3. 金属层走线在 Layer 6/0 (Metal1)
4. PIN marker 在 Layer 255/0

# PAM 示例

本目录包含可运行的示例，演示 PAM 的完整工作流程。

## 示例列表

### 1. L 匹配网络 (`l_match`)

最简单的示例：仅含一个电容和一个传输线。

**文件：**
- `l_match.net` — 原始网表（C1: 1pF, TL1: 50Ohm/1000um）
- `l_match_modified.net` — 修改后网表（C1: 2pF, TL1: 50Ohm/2000um）
- `l_match_modified2.net` — 再修改（C1: 3pF, TL1: 50Ohm/2000um）
- `l_match_initial.gds` — 初始版图

**运行：**
```bash
# 第一次迭代：C1 1pF → 2pF，TL1 1000um → 2000um
pam run \
  --gds examples/l_match_initial.gds \
  --netlist examples/l_match.net \
  --modified-netlist examples/l_match_modified.net \
  --output examples/l_match_updated.gds

# 第二次迭代：C1 2pF → 3pF
pam run \
  --gds examples/l_match_updated.gds \
  --netlist examples/l_match_modified.net \
  --modified-netlist examples/l_match_modified2.net \
  --output examples/l_match_updated_v2.gds
```

---

### 2. Pi 匹配网络 (`pi_match`)

含两个电容、一个电感和一个传输线的 Pi 匹配拓扑。

**文件：**
- `pi_match.net` — 原始网表（C1: 1pF, L1: 2nH, C2: 1pF, TL1: 50Ohm/1000um）
- `pi_match_modified.net` — 修改后网表（C1: 2pF, L1: 3nH, C2: 3pF, TL1: 50Ohm/2000um）
- `pi_match_initial.gds` — 初始版图

**运行：**
```bash
pam run \
  --gds examples/pi_match_initial.gds \
  --netlist examples/pi_match.net \
  --modified-netlist examples/pi_match_modified.net \
  --output examples/pi_match_updated.gds
```

---

### 3. 纯传输线 (`tl_only`)

仅含两条传输线的简单示例。

**文件：**
- `tl_only.net` — 原始网表（TL1: 50Ohm/1000um, TL2: 72Ohm/2000um）
- `tl_only_modified.net` — 修改后网表（TL1: 50Ohm/500um, TL2: 72Ohm/1000um）
- `tl_only_initial.gds` — 初始版图

**运行：**
```bash
pam run \
  --gds examples/tl_only_initial.gds \
  --netlist examples/tl_only.net \
  --modified-netlist examples/tl_only_modified.net \
  --output examples/tl_only_updated.gds
```

---

## 从网表生成初始版图

如果需要从新的网表创建初始 GDS 版图（代替手动布局），使用：

```bash
python scripts/generate_initial_gds.py <netlist.net> <output.gds>
```

**示例：**
```bash
python scripts/generate_initial_gds.py \
  examples/l_match.net \
  examples/my_custom_initial.gds
```

---

## 查看结果

生成的 GDS 文件用 [KLayout](https://klayout.de/) 打开查看。建议使用 0.28 以上版本。

打开 GDS 后：
1. 选择 `TOP` cell 显示
2. 使用 `Shift+F` 放大查看器件细节
3. 金属层走线在 Layer 6/0 (METAL_UNDER)
4. PIN marker 在 Layer 255/0

---

## 网络连接说明

| 网络名 | 连接 | 说明 |
|--------|------|------|
| RFIN | TL1.P1 | RF 输入端口 |
| NET_C1_TL1 | C1.PI → TL1.P2 | 电容到传输线 |
| NET_C1_L1 | C1.NIN → L1.P1 | 电容到电感（Pi 型） |
| NET_L1_C2 | L1.P2 → C2.PI | 电感到电容（Pi 型） |
| GND | C2.NIN | 地 |
| NET_TL1_TL2 | TL1.P2 → TL2.P1 | 传输线级联 |
| RFOUT | TL2.P2 | RF 输出端口 |

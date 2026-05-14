# PAM 使用指南

## 这是什么？

PAM 是一个帮你**自动生成芯片版图**的工具。你告诉它想要的器件参数（比如电容多大、电感多粗），它帮你生成实际的版图文件（GDS）。

---

## 安装（Windows）

### 1. 安装 Python
从 https://www.python.org/downloads/ 下载 Python 3.10+，安装时勾选 **Add Python to PATH**。

### 2. 克隆项目
打开 PowerShell，运行：
```powershell
git clone https://github.com/anycode3/pam-v5.git
cd pam-v5
```

### 3. 安装
```powershell
pip install .
```

---

## 快速开始

项目里自带了示例文件，可以直接试：

```powershell
pam init --netlist examples\l_match.net --params examples\target_params.json --output first.gds
```

成功后会显示：
```
[PAM Init 完成]
  初版GDS: first.gds
  参数快照: state/params_snapshot.json
```

---

## 怎么用？

### 第一步：准备文件

你需要两个文件：

1. **网表文件**（.net）- 从 KiCad 导出的电路连接信息
2. **参数文件**（.json）- 你想要的器件参数

参数文件示例 `params.json`：
```json
[
  {
    "reference": "C1",
    "type": "capacitor_mim",
    "params": {"capacitance_pf": 2.0}
  }
]
```

### 第二步：生成版图

```powershell
pam init --netlist 你的网表.net --params params.json --output layout.gds
```

### 第三步：修改参数后更新版图

改 `params.json` 后运行：

```powershell
pam run --gds layout.gds --netlist 你的网表.net --target params.json --output updated.gds
```

---

## 查看结果

生成的 `.gds` 文件用 **KLayout** 打开查看。

下载地址：https://www.klayout.de/

---

## 常见问题

### Q: `pam : 无法识别`

重新安装：
```powershell
pip install . --force-reinstall
```

### Q: `ModuleNotFoundError: No module named 'klayout'`

安装 KLayout 的 Python 支持：
```powershell
pip install klayout
```

### Q: 安装成功但运行报错

确保关闭 PowerShell 后重新打开，再运行命令。

---

## 命令说明

| 命令 | 用途 |
|------|------|
| `pam init` | 第一次生成版图（冷启动） |
| `pam run` | 修改参数后更新版图（迭代） |

---

有问题？发 issue：https://github.com/anycode3/pam-v5/issues

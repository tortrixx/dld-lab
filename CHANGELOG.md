# CHANGELOG — 变更日志

本项目所有值得记录的变更都会写在这里。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

**变更类型**：`Added` 新增 · `Changed` 修改 · `Fixed` 修复 · `Removed` 删除 · `Docs` 文档

> **使用约定**：每个 commit 对应一条记录。写完代码就跑仿真、跑完仿真就提交、提交完就登记到这里。

---

## [未发布]

### 2026-09-17 · 第 1 次会话 · 项目启动

**Added**
- 建立仓库目录结构：`rtl/` `sim/` `quartus/` `scripts/` `docs/` `report/`
- 新增 `.gitignore`：排除三份课程 PDF（版权材料）与 Quartus 编译产物
- 新增 `CLAUDE.md`：工作约定、硬约束、硬件速查、构建/仿真命令、Commit 规范、文档同步规则
- 新增 `README.md`：项目总览
- 新增过程文档模板：`PROGRESS.md`（跨会话进度）、`CHANGELOG.md`（本文件）、`ERRORS.md`（错误记录）、`AI_LOG.md`（AI 使用记录）

**Docs**
- 完成需求与硬件资料的解码与核实：
  - 逐像素解码题目4 的图4-1 完整图案：点阵第2~5行 × 第2~4列实心 4×3 矩形（12 格）
  - 逐像素解码三块零片形状：6格 `XXX/XX./X..`、3格 `.X/XX`、3格 `XXX`
  - 程序化穷举验证：三块零片恰好有 **2 种合法铺法** → 确立"并集 == 目标掩码"的成功判定准则
  - 从开发板手册核实全部引脚分配、有效电平、位序（DISP7 最左）
  - 核实键盘实物结构：ROW3 在最上排、丝印仅 KEY1~KEY16
  - 从开发板实物照片读取时钟档位丝印：档位 7 = 50MHz
- 确认工具链：Quartus II 9.1（`C:\QuartusII91`），无 ModelSim/GHDL → 仿真采用内置仿真器 + `.vwf`

**Changed**
- 需求冲突处理：题目基本要求3（关卡号显 DISP0）与要求9（显 DISP2）矛盾，**统一取 DISP0**，在文档中说明理由

---

### 2026-09-17 · 第 2 次会话 · 打通自动仿真链路

**Added**
- 新增 `scripts/vwf.py`：Quartus `.vwf` 向量波形文件读写库（解析 / 生成 / 展开嵌套
  `NODE`·`REPEAT`·`LEVEL` / 参考模型比对）。自带自检 `python scripts/vwf.py`
- 新增 `scripts/verify_tiling.py` 入库（穷举验证拼图分解的合法性）

**Changed**
- **仿真方案落地**：确定并实测跑通全自动仿真链路 ——
  `quartus_map --generate_functional_sim_netlist` →
  Python 生成激励 `.vwf` → `quartus_sim --mode=functional --overwrite_waveform=on`
  → Python 解析回写结果并逐点比对参考模型
- 仿真方案由"计划中的 TCL 脚本"改为 **Python**：实测确认 Quartus II 9.1 的
  `::quartus::simulator` 是空包（无任何 Tcl 命令），`quartus_sim -t` 无法驱动仿真

**Fixed**
- 见 `ERRORS.md` 三条记录（均为工具链/引脚问题，非 RTL 缺陷）：
  - ERR-0001 实体名 `exp` 与 Quartus 原语冲突 → 综合失败
  - ERR-0002 内置仿真器无 Tcl 接口且强制要求 `.vwf` → 仿真一度无法自动化
  - ERR-0003 引脚位序与板上网络名混淆 → 差点抄到镜像的点阵列序

**Docs**
- `CLAUDE.md` §5.3 重写为**已实测的**仿真流程（含命令行、`.vwf` 会被覆盖的警告、三个坑）
- `CLAUDE.md` §4.2 新增"引脚号 vs 位序"小节：手册权威引脚表 + 旧工程踩坑说明
- 交叉验证引脚表：与开发板手册、与桌面上 9 个已跑通的旧 Quartus 工程三方核对，
  六组引脚中五组完全一致，唯一差异（红列位序）已定位为旧工程自身命名习惯

---

<!--
## [x.y.z] - YYYY-MM-DD
### Added
### Changed
### Fixed
### Removed
### Docs
-->

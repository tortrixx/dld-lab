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

<!--
## [x.y.z] - YYYY-MM-DD
### Added
### Changed
### Fixed
### Removed
### Docs
-->

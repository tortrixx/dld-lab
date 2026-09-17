# ERRORS — 错误记录

> **用途**：记录项目过程中遇到的一切问题——编译报错、仿真波形不符预期、时序违例、上板异常、设计决策失误……
>
> **为什么认真写**：实验报告评分项⑤"故障及问题分析"**占 15 分**，是第三高单项分。
> 得分点不在"我们没出错"，而在**"定位过程"写得清不清楚**——怎么一步步缩小范围、排除了哪些可能、最后怎么锁定根因。
> 所以**发现问题的当下就要写**，事后回忆必然丢失最有价值的排查细节。

---

## 编号规则

`ERR-0001` 递增。每条记录用下面的五段式 + 状态。

| 字段 | 说明 |
|---|---|
| **现象** | 观察到什么。**原始报错信息原文粘贴**，波形异常要描述清楚哪根信号、什么时刻、什么电平 |
| **定位过程** | ⭐ **最重要**。怎么一步步缩小范围的？做了哪些实验？排除了哪些可能？ |
| **根本原因** | 真正的根因，不是表面症状 |
| **修复方法** | 具体改了什么文件、哪一行 |
| **预防措施** | 以后怎么避免同类问题 |
| **状态** | 已解决 / 未解决 / 已规避 |

---

## 问题索引

| 编号 | 日期 | 标题 | 涉及模块 | 状态 |
|---|---|---|---|---|
| [ERR-0001](#err-0001) | 2026-09-17 | 实体名 `exp` 与 Quartus 原语冲突导致综合失败 | 工具链 | 已解决 |
| [ERR-0002](#err-0002) | 2026-09-17 | 内置仿真器无 Tcl 接口、强制要求 `.vwf` 激励，仿真流程一度无法自动化 | 工具链 / 全部模块 | 已解决 |
| [ERR-0003](#err-0003) | 2026-09-17 | 引脚"位序"与板上"网络名"混淆，差点抄到镜像的点阵列序 | `dot_matrix_scan` | 已规避 |

---

## ERR-0001

**实体名 `exp` 与 Quartus 原语冲突导致综合失败**

- **日期**：2026-09-17
- **阶段**：综合（搭建仿真验证环境时的最小实验工程）
- **涉及模块**：工具链
- **状态**：已解决

### 现象

为验证仿真流程，建了一个最小工程，顶层实体取名 `exp`。执行
`quartus_map simtest --generate_functional_sim_netlist` 时报：

```
Warning: Entity "exp" will be ignored because it conflicts with Quartus II primitive name
Info:    Found 2 design units, including 1 entities, in source file exp.vhd
    Info:    Found design unit 1: exp-rtl
Warning: Entity "exp" will be ignored because it conflicts with Quartus II primitive name
Error:   Top-level design entity "exp" is undefined
Error:   Quartus II Functional Simulation Netlist Generation was unsuccessful. 1 error, 2 warnings
```

### 定位过程

1. **第一反应是路径/工程文件问题** —— 因为报错是 "Top-level design entity is undefined"，
   听起来像是 `TOP_LEVEL_ENTITY` 写错或文件没加进工程。
2. 核对 `.qsf`：`set_global_assignment -name TOP_LEVEL_ENTITY exp` 与实体名一致；
   `VHDL_FILE exp.vhd` 也在。**排除配置错误**。
3. **注意到了一个"多余"的信息**：`Found design unit 1: exp-rtl` —— 说明 VHDL 文件
   **被成功解析了**，实体确实存在。那"undefined"就只可能是**被主动丢弃**了。
4. 回头看上面那两条 Warning：`conflicts with Quartus II primitive name`。
   **这才是根因，Error 只是它的后果。**
5. 验证：把实体名改成 `simtest`（同时改文件名、`TOP_LEVEL_ENTITY`、`.qsf` 里的
   `VHDL_FILE`），重新综合 → `0 errors, 0 warnings`。**确认根因**。

### 根本原因

`exp` 是 Quartus 内置的 LPM 原语名（指数运算 megafunction）。Quartus 的综合器
把用户实体匹配到原语库时**优先**认定它是原语，于是把用户这个实体忽略掉，
导致顶层实体找不到。

### 修复方法

- 文件：实验工程 `simtest.vhd`（临时实验，未进仓库）
- 改动：实体名 `exp` → `simtest`，并同步改文件名与 `.qsf` 中
  `TOP_LEVEL_ENTITY` / `VHDL_FILE`

### 预防措施

- **实体命名避开 Quartus 原语名**。高危名单：`exp`、`abs`、`add`、`sub`、`mult`、
  `div`、`lpm_*`、`alt*`、`mux`、`decode`。
- 本项目模块名（`puzzle_pkg` / `clk_gen` / `seg_scan` / `dot_matrix_scan` /
  `keypad_scan` / `pattern_rom` / `piece_rom` / `rng_lfsr` / `puzzle_ctrl` /
  `disp_format` / `game_fsm` / `buzzer_ctrl` / `puzzle_top` / `board_test_top`）
  **均已核对，无冲突**。
- **通用教训**：综合报错时，"Warning" 往往才是根因，"Error" 只是它的下游后果。
  排查时要**从第一条 Warning 读起**，而不是盯着最后的 Error。

---

## ERR-0002

**内置仿真器无 Tcl 接口、强制要求 `.vwf` 激励，仿真流程一度无法自动化**

- **日期**：2026-09-17
- **阶段**：搭建仿真验证环境
- **涉及模块**：工具链 / 全部模块
- **状态**：已解决

### 现象

本机没有 ModelSim / GHDL，只能用 Quartus II 9.1 内置仿真器。计划里写的是
"脚本生成 `.vwf` → 命令行跑仿真 → 脚本解析结果"，但在实施时连续撞墙：

```
Error: No valid vector source file specified and default file
       "...\simtest.cvwf" does not exist
```

即使指定了 `--simulation_results_format=VCD`，仿真"成功"后也**不产生任何 VCD 文件**；
`.sim.rpt` 里关于波形的部分只有一句：

```
Waveform report data cannot be output to ASCII.
Please use Quartus II to view the waveform report data.
```

### 定位过程

1. **先假设有 Tcl 接口**。查 `quartus_sim --help`，发现支持 `-t <script file>`，
   于是写脚本 `package require ::quartus::simulator`。
   结果：**包能加载成功**，但 `info commands simulator_*` 返回空列表。
2. **换 `quartus_sh` 再试**，对比 `package require` 前后的 `info commands`，
   新增的只有 `pkg_mkIndex` / `tclPkgSetup` 之类 Tcl 自举命令。
   → **结论：9.1 的 `::quartus::simulator` 是个空壳包，没有可用的 Tcl API。**
3. **回到"必须提供向量源文件"这条路**。先尝试把格式从 Quartus 自带的帮助/示例里找出来：
   - 整个 Quartus 安装目录里 `find -iname "*.vwf"` → **零个样例文件**
   - 官方 VHDL 入门教程 PDF 只讲概念，不给格式
   - 从 `db_vdb.dll` 里提取字符串，找到 `vdb_vec_lexer.cpp` / `vdb_vec_parser.ypp` /
     "Pattern Section" 等线索 → 确认**存在文本格式解析器**，但**语法仍拼不出来**
4. **转折点：转换思路，去机器上找现成的 `.vwf`**。
   在用户桌面发现 `C:\Users\sznnn\Desktop\VHDL\` 下有 **9 个此前做过的 Quartus 工程**，
   每个都带 `.vwf` / `.pin` / `.sim.rpt` —— **这些是曾经在开发板上跑通过的**。
   读 `mux4/mux4.vwf` 后，`.vwf` 的文本格式**一次性完全确定**。
5. **验证格式**：按学到的格式手写一个 `.vwf` 喂给 `quartus_sim`，
   仿真成功（`0 errors`），并且发现关键行为——
   **加 `--overwrite_waveform=on` 后，仿真结果会被写回输入 `.vwf` 本身**，
   每个节点都变成可解析的 `TRANSITION_LIST`。

### 根本原因

三个独立的事实叠加，导致"照常规思路自动化"走不通：

1. Quartus II 9.1 的仿真器**故意不提供 Tcl API**（该功能是给 GUI 用的）；
2. 它的输入向量格式**在安装包里既无文档也无样例**；
3. 它的 ASCII 报告**从不包含波形数据**，结果只能通过回写 `.vwf` 拿到。

### 修复方法

- 文件：`scripts/vwf.py`（新增）
- 改动：把 `.vwf` 的读写封装成库——解析嵌套 `NODE`/`REPEAT`/`LEVEL` 结构、
  展开成时间序列、生成激励、保证 `DISPLAY_LINE` 自洽。
  `scripts/vwf.py` 自带自检：`python scripts/vwf.py` 打印 `自检通过 ✓`。
- 确定了可用的命令行：

```bash
quartus_map  <工程> --generate_functional_sim_netlist
quartus_sim  <工程> --mode=functional --overwrite_waveform=on
```

- 做**往返验证**：Python 生成激励 → 仿真 → 解析回写结果 → 与参考模型
  **逐点比对 100 个采样点**，全部通过。至此仿真流程**完全自动化且自校验**。

### 预防措施

- **`.vwf` 会被仿真结果覆盖** → 激励必须可重新生成，永远不手工编辑 `sim/*.vwf`。
- 不要再去找 VCD 输出（`--simulation_results_format=VCD` 实测不产生文件），
  也不用去 `.sim.rpt` 里找波形。
- **通用教训（这条最值钱）**：
  工具链卡住时，**先去本机找"已经跑通过的同类产物"**，比啃文档、逆向二进制快得多。
  这次如果在第 3 步之后继续死磕 `db_vdb.dll`，会白耗大量时间；
  而桌面上的 9 个旧工程一读就通。**"存在可工作的样例"本身就是最权威的格式文档。**
- 副产品：顺带确认了本项目引脚表与旧工程一致（见 ERR-0003）。

---

## ERR-0003

**引脚"位序"与板上"网络名"混淆，差点抄到镜像的点阵列序**

- **日期**：2026-09-17
- **阶段**：引脚约束编写 / 交叉验证
- **涉及模块**：`dot_matrix_scan`、`quartus/puzzle.qsf`
- **状态**：已规避（未造成实际损失）

### 现象

编写 `quartus/puzzle.qsf` 的点阵列引脚时，用桌面上已跑通的旧工程
`VHDL/dot_matrix_pwm/dot_matrix_pwm.qsf` 做交叉验证，发现**两者相反**：

| 信号 | 本项目 `puzzle.qsf` | 旧工程 `dot_matrix_pwm.qsf` |
|---|---|---|
| 红色列 第 0 位 | `PIN_22` | `PIN_11` |
| 红色列 第 7 位 | `PIN_11` | `PIN_22` |

若照着旧工程抄，点阵图案会**左右镜像**——而且因为图案本身大致对称时不易察觉，
很可能拖到上板验收才被发现。

### 定位过程

1. 先怀疑**手册读错了**。回到开发板手册原文重新提取，得到：

   > `COLR0~COLR7 依次使用 EPM1270T144C5 芯片的 22、21、16、15、14、13、12 和 11 脚`

   → 手册明确：**COLR0 = 22，COLR7 = 11**。本项目写法与手册一致。

2. 那旧工程为什么反着写还能跑？去读它的扫描代码，确认它的内部信号 `col_r`
   是**独立命名**的，与板上 `COLRn` 丝印没有绑定关系——它的扫描逻辑按自己的
   `col_r` 顺序写，所以自洽可用。

3. **关键判断**：不能因为"旧工程能跑"就认定"旧工程的位序是权威的"。
   权威的只有**手册里的物理网络名**。旧工程只能用来确认
   "这块板子用到了哪些引脚"（这一项它完全对上了：行 8~1、绿列 38~45 与本项目**逐条一致**），
   但不能用来确定位序。

4. 顺带用同一方法核对了**段码、位选、LED**：

   | 组 | 旧工程（多个工程一致） | 本项目 | 结论 |
   |---|---|---|---|
   | 点阵行 ROW0~7 | 8,7,6,5,4,3,2,1 | 同 | ✅ 一致 |
   | 点阵绿列 COLG0~7 | 38,39,40,41,42,43,44,45 | 同 | ✅ 一致 |
   | 数码管段 | 62=AA,59=AB,…,52=AG,51=AP | 同 | ✅ 一致 |
   | 数码管位选 CAT0~7 | 63,66,67,68,69,70,30,31 | 同 | ✅ 一致 |
   | LED LD0~15 | 80,79,…,73,144,143,…,137 | 同 | ✅ 一致 |
   | 全局时钟 | 18 | 同 | ✅ 一致 |

   六组里五组完全一致，**只有红列一组是旧工程反着写的** —— 这反而印证了
   "旧工程的差异是它自己的命名习惯，不是手册读错"。

### 根本原因

**"信号的第 n 位"和"板上丝印的第 n 号网络"是两个独立的东西。**
旧工程把 `col_r[0]` 接到了物理上的 `COLR7`，只要它的扫描代码按 `col_r` 的顺序写，
功能就正确——但**引脚表本身已经不再对应手册的命名**。
直接复用这样的引脚表，就等于悄悄引入了一次位序反转。

### 修复方法

- 文件：`quartus/puzzle.qsf`（保持不变，它本来就是对的）
- 改动：**无**。本次是**验证**，不是修复。
- 追加防护：在 `CLAUDE.md` §4.2 增加"引脚号 vs 位序"小节，把对照表和这个坑写死。

### 预防措施

- **引脚号只从开发板手册拿。** 旧工程/网上代码只能用来交叉验证
  "用到了哪些引脚"，**不能用来确定位序**。
- 位序约定必须**全项目单点定义**（本项目写在 `rtl/puzzle_pkg.vhd` 与
  `CLAUDE.md` §4.2），不允许各模块各自解释。
- 上板前用 `board_test_top` 自检工程**逐列点亮**，直接肉眼确认
  `dot_colr(0)` 对应的是不是最左列——这是唯一能一锤定音的验证。

---

<!--
=====================================================================
 复制下面的模板新增记录
=====================================================================

## ERR-0001 <一句话标题>

- **日期**：2026-09-17
- **阶段**：模块编写 / 仿真 / 综合 / 布局布线 / 上板
- **涉及模块**：
- **状态**：未解决

### 现象

（原文粘贴报错信息，或详细描述波形/板级异常）

### 定位过程

1.
2.
3.

### 根本原因

### 修复方法

- 文件：`rtl/xxx.vhd` 第 N 行
- 改动：

### 预防措施

-->

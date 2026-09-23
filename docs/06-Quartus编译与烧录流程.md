# 06 · Quartus 编译与烧录流程（Windows）

> 面向《数字电路与逻辑设计实验（下）》题目 4《简易拼图游戏的设计与实现》。
> 目标器件 **Altera MAX II `EPM1270T144C5`**（144 脚 TQFP）· 工具 **Quartus II 9.1**
> 本文给出**从零建工程 → 编译 → 引脚分配 → 下载烧录**的完整分步操作，
> 以及本工程已实测通过的编译结果与常见报错处置。
>
> ✅ **实测结论（2026-09-23，本机 Quartus II 9.1 Build 222）**
>
> | 顶层 | 逻辑单元 | 引脚 | Fmax | 结论 |
> |---|---|---|---|---|
> | `board_test_top`（硬件自检） | **439 / 1270（35%）** | 68 / 116 | — | 全流程编译通过 ✓ |
> | `puzzle_top`（整机拼图） | **1226 / 1270（97%）** | 52 / 116 | **63.66 MHz** | 全流程编译通过、时序收敛 ✓ |
>
> 资源余量很小（整机只剩 44 个 LE），**改动代码后务必看编译报告的 LE 数**。

---

## 0. 两条使用路径（先看清怎么走）

| 路径 | 适用 | 做什么 |
|---|---|---|
| **路径 A（推荐）** | 直接用本仓库已建好的工程 | 打开 `quartus/puzzle.qpf` → 编译 → 烧录 |
| **路径 B** | 实验报告要求"从零建工程"，或想自己重排 | 按 §1 新建工程，把 `rtl/` 下 14 个 `.vhd` 加进去 |

> ⚠️ **工程一次只能有一个顶层**。本仓库 `quartus/puzzle.qsf` 里默认顶层是
> **`board_test_top`（硬件自检）**，因为它必须在**第一次进实验室之前**就能编译好
> （`docs/01` §8）。要玩整机拼图，按 **§5** 切换顶层（两步）。

---

## 1. 建立工程（路径 B；路径 A 可跳过）

### 1.1 新建工程向导

1. 启动 Quartus II 9.1：开始菜单 → **Quartus II 9.1**。
2. 菜单 **File → New Project Wizard** → Next。
3. **Directory, Name, Top-Level Entity**
   - 工作目录：选到仓库的 `quartus/` 文件夹（**不要选中文路径**）
   - 工程名：`puzzle`
   - 顶层实体名：先填 `board_test_top`（后面可改）
4. **Add Files**：把 `rtl/` 下这 14 个文件全部加入（Add → 逐个选，或直接选目录里全部 `.vhd`）：
   ```
   puzzle_pkg.vhd   clk_gen.vhd     keypad_scan.vhd   seg_scan.vhd
   dot_matrix_scan.vhd  pattern_rom.vhd  piece_rom.vhd  rng_lfsr.vhd
   puzzle_ctrl.vhd  disp_format.vhd  game_fsm.vhd     buzzer_ctrl.vhd
   puzzle_top.vhd   board_test_top.vhd
   ```
   > ⚠️ `puzzle_pkg.vhd` 是**包**不是实体，但**必须**加进工程，否则所有模块的
   > `use work.puzzle_pkg.ALL;` 都找不到定义。
5. **Family & Device**：Family = `MAX II`，Device = **`EPM1270T144C5`**
   （144 脚 TQFP、C5 速度等级 —— 选错器件会导致引脚号全部对不上）。
6. **EDA Tool Settings**：全部保持 `<None>`（仿真用 Quartus 自带仿真器）。
7. Finish。

### 1.2 必做的三项工程设置

菜单 **Assignments → Settings**（或写进 `.qsf`）：

| 项 | 位置 | 值 | 为什么 |
|---|---|---|---|
| VHDL 输入版本 | **Analysis & Synthesis Settings → VHDL Input** | **VHDL 1993** | 本工程代码是 VHDL-93 子集（不用 2008 语法） |
| 综合优化目标 | **Analysis & Synthesis Settings → Optimization Technique** | **Area** | 课件 p50 例4 明确要求；EPM1270 只有 1270 个 LE，且本设计对速度无要求。**默认是 Balanced，必须显式改** |
| 未使用引脚 | **Device → Unused Pins** | **As input tri-stated** | 避免悬空引脚意外驱动外部器件 |

> 这三项在本仓库 `quartus/puzzle.qsf` 里**已经写好**，路径 A 无需再设。

### 1.3 时序约束（可选但建议）

`quartus/puzzle.sdc` 已经写好 50MHz 时钟定义：

```tcl
create_clock -name clk -period 20.000 -waveform {0.000 10.000} [get_ports {clk}]
```

在 **Assignments → Settings → Timing Analysis Settings** 里把它加入（或 `.qsf` 里
`set_global_assignment -name SDC_FILE puzzle.sdc`）。编译后用它读 **Fmax**。

---

## 2. 引脚分配

### 2.1 分配依据（重要）

- **引脚号只认开发板手册**《MAXII数字实验板（LCM12864液晶版）》；
- 本仓库**已经把 68 个引脚写死在 `quartus/puzzle.qsf`**，并用手册逐条核对过
  （可读版对照表见 `docs/04-引脚分配表.md` §2）；
- ⚠️ **不要用别的旧工程抄引脚表**：本机另一个旧工程把 `col_r[0]` 接在 `PIN_11`
  （手册里的 COLR7），位序与手册相反 —— 抄它会得到**左右镜像**的点阵（ERR-0003）。

### 2.2 用 GUI 分配（路径 B 或需要临时改动时）

菜单 **Assignments → Pins**（引脚规划器）→ 在 **Location** 列填 `PIN_xx`：

| 功能 | 端口 | 引脚号 |
|---|---|---|
| 全局时钟 | `clk` | `PIN_18` |
| 系统开关 | `sw7` | `PIN_125` |
| 复位键 BTN0 | `btn` | `PIN_61` |
| 点阵行（低有效） | `dot_row[7:0]` | `PIN_8,7,6,5,4,3,2,1` |
| 点阵红列（高有效） | `dot_colr[7:0]` | `PIN_22,21,16,15,14,13,12,11` |
| 点阵绿列（高有效） | `dot_colg[7:0]` | `PIN_45,44,43,42,41,40,39,38` |
| 数码管段（高有效） | `seg[7:0]` | `PIN_62,59,58,57,55,53,52,51` |
| 数码管位选（低有效） | `cat[7:0]` | `PIN_63,66,67,68,69,70,30,31` |
| 键盘列（扫描输出） | `kp_col[3:0]` | `PIN_117,118,119,120` |
| 键盘行（读入，按下=1） | `kp_row[3:0]` | `PIN_111,112,113,114` |
| 蜂鸣器 | `buzz` | `PIN_60` |
| 16 个 LED（**仅自检顶层**） | `ld[15:0]` | `PIN_80,79,78,77,76,75,74,73,144,143,142,141,140,139,138,137` |

> ⚠️ **`ld[15:0]` 只属于 `board_test_top`**。整机顶层 `puzzle_top` 没有这个端口，
> 若此时 `.qsf` 里还留着这 16 行约束，编译会在 fitter 阶段报
> "分配到不存在端口的引脚" —— 所以 §5 切换顶层时**必须同时注释掉它们**。

### 2.3 分配后一定要做的一致性检查（本仓库自带脚本）

```bash
python scripts/check_pins.py             # 比对 .qsf 与手册抄件
python scripts/check_pins.py --selftest  # 负向测试：证明这个检查器真能抓错
```

---

## 3. 编译（综合 → 布局布线 → 汇编）

### 3.1 GUI 方式

菜单 **Processing → Start Compilation**（快捷键 `Ctrl+L`）→ 等待
（本工程整机约 20~40 秒）→ 看提示 **Successful** 或 **Error**。

### 3.2 命令行方式（本仓库推荐，能自动打印资源与 Fmax）

```bash
# 全流程（按 .qsf 里当前顶层）
"C:/QuartusII91/QuartusII91/quartus/bin/quartus_sh.exe" -t scripts/build.tcl

# 只做综合（最快，用来查语法错）
"C:/QuartusII91/QuartusII91/quartus/bin/quartus_sh.exe" -t scripts/build.tcl --map-only

# 临时换顶层编译一次（脚本自带"用完还原"，不会污染 .qsf）
"C:/QuartusII91/QuartusII91/quartus/bin/quartus_sh.exe" -t scripts/build.tcl --top puzzle_top
```

分步执行（等价，便于定位是哪一步出错）：

```bash
quartus_map puzzle     # Analysis & Synthesis：语法/综合
quartus_fit puzzle     # Fitter：布局布线 + 引脚
quartus_asm puzzle     # Assembler：生成 .pof 烧录文件
quartus_tan puzzle     # 经典时序分析（Fmax）
quartus_sta puzzle     # TimeQuest 时序分析（Fmax，本工程用这个读数）
```

### 3.3 产物在哪

```
quartus/output_files/puzzle.sof   # JTAG 下载用（SRAM 目标，掉电即失）
quartus/output_files/puzzle.pof   # 配置闪存用（掉电不丢，推荐）
quartus/output_files/puzzle.fit.rpt / .fit.summary   # 资源利用率（报告评分项④）
quartus/output_files/puzzle.sta.rpt                  # Fmax
```

### 3.4 本工程实测结果（可直接写进实验报告）

- `board_test_top`：**439 LE / 1270（35%）**，68 引脚
- `puzzle_top`：**1226 LE / 1270（97%）**，52 引脚，**Fmax 63.66 MHz ≥ 50 MHz** ✓

---

## 4. 下载烧录（把配置写进板子）

### 4.1 硬件连接

1. 把 **USB-Blaster 下载线**一头插电脑 USB、另一头插开发板 **JTAG 口**
   （板子在实验室内使用，**不要带出实验室**）。
2. 开发板**接通电源**（电源指示亮）。
3. 用**右上角 `USER_BTN`** 把板载时钟档位切到 **7（50MHz）**（档位指示灯确认）。

### 4.2 Quartus 里打开编程器

菜单 **Tools → Programmer** → 自动弹出 Programmer 窗口。

1. 点 **Hardware Setup...** → 选 **USB-Blaster** → Close。
   - 若列表里没有：先装 USB-Blaster 驱动（设备管理器 → 未知设备 → 更新驱动 →
     指向 `C:\QuartusII91\QuartusII91\quartus\drivers\usb-blaster`）。
2. 点 **Auto Detect** → 应识别出 **EPM1270**。
   - 识别不到：检查 JTAG 排线方向、板子电源、有没有别的人占用下载线。
3. 点 **Add File...** → 选 `quartus/output_files/puzzle.pof`。
   - ⚠️ 用 **`.pof`**（配置闪存）而不是 `.sof`：`.pof` 掉电不丢，
     教师验收时重新上电即用；`.sof` 只写 SRAM，掉电就没了。
4. 勾选 **Program/Configure**（如果要烧到板载配置闪存，通常同时勾
   **Program/Configure** 即可；部分板子还需勾 **Verify**）。
5. 点 **Start** → 进度条到 100%、显示 **Successful** 即完成。
6. 把 **SW7 拨到 "1"（开）** → 观察板子：点阵全黄 2Hz 闪烁、8 位数码管全显 "8"
   且闪烁（这就是要求 1 的开机自检）。

### 4.3 命令行烧录（等价操作，便于脚本化）

```bash
quartus_pgm -c USB-Blaster -m jtag -o "p;quartus/output_files/puzzle.pof"
```

参数含义：`-c` 下载线型号 · `-m jtag` 模式 · `p;文件` = program + 文件名。

---

## 5. 在"硬件自检"与"整机拼图"之间切换顶层

`.qsf` 里**源文件已经全部登记**，切换只需要改两处：

| # | 改什么 | 位置 |
|---|---|---|
| 1 | `set_global_assignment -name TOP_LEVEL_ENTITY <顶层名>` | `quartus/puzzle.qsf` 第 15 行附近 |
| 2 | **16 行 `ld[…]` 引脚约束**：编 `puzzle_top` 时注释掉；切回 `board_test_top` 时恢复 | `quartus/puzzle.qsf` 文件末尾「16 个 LED」一节 |

- 切到 **`puzzle_top`（整机）**：改第 1 处为 `puzzle_top` + 注释掉那 16 行。
  （这一步是 `docs/02` §14.1.4「阶段 4 工程迁移三步」的第 2、3 步，第 1 步——加源文件——已经做完。）
- 切回 **`board_test_top`（自检）**：改回 `board_test_top` + 取消那 16 行的注释。

> ⚠️ **不能用 `scripts/build.tcl --top` 代替这两步**：`--top` 只改顶层名，
> 解决不了 `ld` 约束悬挂的问题（fitter 会报"引脚分配给不存在的端口"）。

---

## 6. 常见报错与处置（本工程实际遇到过的）

| 现象 | 原因 | 处置 |
|---|---|---|
| `Error: Design contains N blocks of type logic cell. However, device contains only 1270` | LE 超了（最初版本 3461） | 已通过"行扫描引擎时分复用 + 包围盒判据"降到 1226；再超时先看编译报告的 by-entity 表 |
| `Can't resolve multiple constant drivers for net "xxx"` | 同一信号被两个进程赋值（课件 p58 的多重驱动） | 把写者归并到一个进程（本工程设计时已按此规则，见 `docs/02` §10.5） |
| `VHDL error: can't determine definition of operator "&"` | 字符串字面量类型不明确（如 `"000" & i_level`） | 改成 `if i_level = '0' then …` 或显式类型转换 |
| `VHDL Type Conversion error: cannot convert type "std_logic" to "UNSIGNED"` | 把 1 位 `std_logic` 直接转 `unsigned` | 先拼成向量或改用 `if` 判断 |
| `Warning (13410): Pin "seg[7]" is stuck at GND` | 数控小数点 AP 段未使用 | 可忽略（`docs/02` §5.5 已说明 AP 保留不用） |
| 编译通过但**点阵左右镜像 / 上下颠倒** | 点位序与板子实际不一致 | 只改 `puzzle.qsf` 里 `dot_colr`/`dot_colg`（镜像）或 `dot_row`（颠倒）的顺序，**代码与位序约定不动**（`docs/04` §3.1） |
| 按键全部无反应 | 键盘极性/行列与实际相反 | 先烧 `board_test_top` 用阶段 7 自检确认（`docs/01` §8.2） |
| Fmax < 50MHz | 组合路径过长 | 在长路径中间打一拍寄存（本工程已用：图案选择寄存、判定单独一拍、包围盒判据寄存一拍） |

---

## 7. 第一次进实验室的推荐动作顺序（时间宝贵）

1. **烧 `board_test_top`**（顶层保持默认即可），按 `docs/01` §8.2 的 **9 个阶段**逐条打勾：
   时钟档位 → 点阵行序/极性 → 列序/极性 → 数码管位选/段码 → 键盘 → 蜂鸣器高低音 → BTN0 复位。
2. 把结果记入 `docs/05-硬件调试记录.md`（含异常 → 记 `ERRORS.md`）。
3. 切顶层为 `puzzle_top`（§5），重新编译烧录，按 `docs/02` §14.3 的 13 个场景验收。
4. **顺手录一段工作视频**（课件 p65 的提交物之一，出了实验室补不出来）。
5. 若点阵左右镜像 / 上下颠倒 / 数码管偏暗，按 §6 与 `docs/02` §5.6 的备选方案处理。

> ⚠️ 每班只有 3 块实验板（课件 p64），**先在"Easy 云课堂"预约**（可预约窗口 =
> 实验开始前 7 天 ~ 开始前 30 分钟），并按时签到（至少 2 次）。

# -*- coding: utf-8 -*-
"""tb_keypad_scan.py —— keypad_scan 的 **2×2 极性交叉测试**（ERR-0035 回归）

【本 tb 要修掉的假绿（独立审计 P0-1）】
    上一版把板子模型**绑死在代码假设上**：`IDLE = 1 - KP_ACTIVE`。
    于是第 2 轮（KP_ACTIVE='1'）把"未按下的行"驱成 **0** —— 那是**下拉板**，
    而真实板是**上拉**（无键时行读到 '1'，见 ERR-0035 / `rtl/keypad_scan.vhd:48-54`）。
    结果"高有效 RTL + 上拉真实板"这个**真正会误报**的组合**从来没被跑到**，
    "两种极性都测"给了虚假信心。**本版把两件事彻底解耦：**

        · `KP_ACTIVE`（代码假设） —— 只通过 `RTL_PATCHES` 翻 RTL 里的常量；
        · `board_idle`（板子模型） —— **只**决定 tb 怎么驱动 `i_kp_row` 的空闲电平。

【2×2 交叉矩阵】（本 tb 的全部要点）
    ┌────┬────────────┬───────────────────────┬───────────────────────────────┐
    │ 格 │ KP_ACTIVE  │ 板子模型（行空闲电平） │ 文档预测                      │
    ├────┼────────────┼───────────────────────┼───────────────────────────────┤
    │ 1  │ '0' 低有效 │ 高（上拉，**真实板**）│ 不得误报                      │
    │ 2  │ '0' 低有效 │ 低（下拉板）          │ 不得误报（docs/04 §3.3 的说法）│
    │ 3  │ '1' 高有效 │ 高（上拉，**真实板**）│ ⭐ **必须复现 ERR-0035**       │
    │ 4  │ '1' 高有效 │ 低（下拉板）          │ 不误报                        │
    └────┴────────────┴───────────────────────┴───────────────────────────────┘

    第 3 格是关键：**旧代码（高有效）在真实板（上拉）上必然误报** ——
    无键时 4 行全读到 '1'，RTL 判 `= '1'` 即"按下"，循环里**行号最大者胜出**，
    于是每相都得到幻影键号 `phase + 1`，整轮锁存 **4 =「开始」**
    （`game_fsm` L155 `when "00100" => s_act_start`）→ 触发全局边踢出自检态。
    本 tb **断言这个误报一定会发生**，并打印实际幻影键号。

【板子模型怎么来的】
    `kp_row = 0xF`（全高）= 上拉板空闲；`kp_row = 0x0`（全低）= 下拉板空闲。
    真实按键 = 把该键所在行、在**它自己那一相**驱到代码假设的"按下"电平（`KP_ACTIVE`）。

【怎么跑 4 格】（轮次号自动递增，同一命令连跑 4 次即得 r03~r06）
    格号由"下一条轮次号"推出：r03→格1、r04→格2、r05→格3、r06→格4。
    也可用环境变量显式指定：`KP_CELL=3 python scripts/sim.py run keypad_scan`。

【激励时间线】（单位 ns；clk 20ns、i_tick 每 40ns 一拍）
    A 无键        26 轮 → 误报检测（≥21 轮，足以让幻影键出脉冲）
    B 按住 KEY2   26 轮 → 真实按键（键号 / 消抖时长 / 脉冲宽度）
    C 松开        26 轮 → 归零检查
    合计 78 轮 = 312 tick = 12480 ns。
"""

import os
import pathlib
import re

# ============================================================
# 0. 2×2 交叉矩阵：代码假设（KP_ACTIVE）× 板子模型（行空闲电平）
# ============================================================
ROOT = pathlib.Path(__file__).resolve().parent.parent
_ROUNDS_DIR = ROOT / "sim" / "rounds" / "keypad_scan"

# 每格 = (格号, KP_ACTIVE, board_idle, 文档预测"会误报"?, 说明)
#   KP_ACTIVE  : 代码假设的"按下"电平（'0' 低有效=当前默认；'1' 高有效=旧错法）
#   board_idle : 板子模型 —— 无按键时行读到什么（真实板=1 上拉；下拉板=0）
#   doc_fr     : 文档（任务表 / docs/04 §3.3）预测该格**会**误报吗
CELLS = [
    (1, 0, 1, False, "低有效 RTL + 上拉板（真实板）"),
    (2, 0, 0, False, "低有效 RTL + 下拉板"),
    (3, 1, 1, True,  "高有效 RTL（旧错法）+ 上拉板（真实板）→ ERR-0035"),
    (4, 1, 0, False, "高有效 RTL + 下拉板"),
]


def _existing_rounds():
    if not _ROUNDS_DIR.exists():
        return 0
    return sum(1 for f in _ROUNDS_DIR.iterdir() if re.match(r"r\d+\.json$", f.name))


def _select_cell_no():
    forced = os.environ.get("KP_CELL", "").strip()
    if forced:
        return int(forced)
    nxt = max(_existing_rounds() + 1, 3)
    return ((nxt - 3) % 4) + 1


CELL_NO = _select_cell_no()
_KEYS = {c[0]: c for c in CELLS}
if CELL_NO not in _KEYS:
    raise SystemExit("✗ KP_CELL=%r 无效（应为 1~4）" % CELL_NO)
_CELL = _KEYS[CELL_NO]

KP_ACTIVE = _CELL[1]                 # 代码假设的"按下"电平
BOARD_IDLE = _CELL[2]                # 板子模型：行空闲电平（与代码假设**独立**）
DOC_EXPECT_FALSE_REPORT = _CELL[3]   # 文档预测
CELL_LABEL = _CELL[4]

ACTIVE = KP_ACTIVE                   # 选中列的驱动电平 = 代码假设的"按下"电平
IDLE_ROW = BOARD_IDLE                # 未按键时行读到什么
# 板型判定规则：行空闲电平 == 代码假设的"按下"电平 ⇒ 无键也被读成"按下" ⇒ 必误报
PHYSICS_FALSE_REPORT = (IDLE_ROW == ACTIVE)
MATCHED = not PHYSICS_FALSE_REPORT

POLARITY = "高有效" if KP_ACTIVE == 1 else "低有效"
BOARD_KIND = "上拉板（行空闲=1）" if BOARD_IDLE == 1 else "下拉板（行空闲=0）"

# 高有效 = 旧错法 → 用 RTL_PATCHES 把 RTL 的常量翻成 '1'（只作用于隔离副本）
if KP_ACTIVE == 1:
    RTL_PATCHES = [
        ("rtl/keypad_scan.vhd",
         "constant KP_ACTIVE : std_logic := '0';",
         "constant KP_ACTIVE : std_logic := '1';"),
    ]
else:
    RTL_PATCHES = []

# ============================================================
# 1. 时序常量与激励
# ============================================================
CLK_PERIOD = 20.0            # 50MHz 等价
TICK_PERIOD = 40.0           # i_tick 每 2 个 clk 来一拍
TICK_REAL_MS = 1.0           # 一个 i_tick = 1ms（折算真实时间用）

PHASE_ROUNDS = 26            # 每阶段 26 轮（> 21 轮消抖，足以让幻影键出脉冲）

TICKS = []
TICKS += [0] * (4 * PHASE_ROUNDS)   # A 无键
TICKS += [2] * (4 * PHASE_ROUNDS)   # B 按住 KEY2
TICKS += [0] * (4 * PHASE_ROUNDS)   # C 松开
N = len(TICKS)

DURATION = N * TICK_PERIOD
GRID_PERIOD = TICK_PERIOD

I_A0 = 0
I_B0 = 4 * PHASE_ROUNDS               # 104
I_C0 = 8 * PHASE_ROUNDS               # 208
I_END = 12 * PHASE_ROUNDS             # 312

I_B_R1END = I_B0 + 3                  # Phase B 第 1 个轮末
I_B_PULSE = I_B0 + 83                 # Phase B 第 21 个轮末（消抖完成）
I_A_PULSE = 83                        # Phase A 第 21 个轮末（幻影脉冲若出现）


# ============================================================
# 2. 参考模型（期望值来自 docs/04 §3.3 的键号公式，非抄 RTL 常量）
#    键号 = (3-ROW)*4 + COL + 1  ⇒  ROW = 3-(KEY-1)//4、COL = (KEY-1)%4
# ============================================================
def _key_row_col(key):
    return (3 - (key - 1) // 4, (key - 1) % 4)


def _rowval(key, phase):
    """第 `phase` 相扫描、当前按住的键为 `key` 时，行输入应为的电平（4 位整数）。"""
    val = 0
    for r in range(4):
        b = IDLE_ROW
        if key != 0:
            krow, kcol = _key_row_col(key)
            if r == krow and phase == kcol:
                b = ACTIVE          # 该键把"选中列"的驱动电平接到行上
        val |= b << r
    return val


def _colpat(phase):
    """列驱动参考模型：恰好第 `phase` 位 = ACTIVE（选中列），其余 = 1-ACTIVE。"""
    return sum((ACTIVE if b == phase else 1 - ACTIVE) << b for b in range(4))


# ============================================================
# 3. 观测点（中间信号缺失即报错，docs/03 §3.1 第 5 条）
# ============================================================
OBSERVE = [
    "clk", "rst", "i_tick", "i_kp_row",
    "o_kp_col", "o_key_code", "o_key_press",
    "r_phase", "r_stable", "r_down", "r_cnt",
]


def build(b):
    b.input_bit("clk")
    b.input_bit("rst")
    b.input_bit("i_tick")
    b.input_bus("i_kp_row", 4)

    b.output_bus("o_kp_col", 4)
    b.output_bus("o_key_code", 5)
    b.output_bit("o_key_press")

    # 中间信号：声明为输出（不由 tb 驱动）→ 由仿真回写
    b.output_bus("r_phase", 2)
    b.output_bus("r_stable", 5)
    b.output_bit("r_down")
    b.output_bus("r_cnt", 5)

    b.clock("clk", CLK_PERIOD)
    # ⚠️ 时序模块必须显式给复位（综合后网表寄存器初值是 X，不是 0）
    b.segments("rst", [(20.0, 1), (DURATION - 20.0, 0)])
    # i_tick：每个 tick 末尾一个 clk 宽的高电平（对齐到一个 clk 上升沿）
    b.segments("i_tick", [(TICK_PERIOD - CLK_PERIOD, 0), (CLK_PERIOD, 1)] * N)

    # 行输入：逐 tick 给出，正好在每个 tick 的 clk 上升沿保持稳定
    b.bus_segments("i_kp_row", [(TICK_PERIOD, _rowval(TICKS[i], i % 4))
                                for i in range(N)])


# ============================================================
# 4. 采样辅助
# ============================================================
def _t_edge(i):
    """第 i 个（0 基）tick 的 clk 上升沿时刻。"""
    return TICK_PERIOD * (i + 1) - CLK_PERIOD / 2.0


def _t_after(i):
    """第 i 个 tick 更新之后（读输出用）。"""
    return _t_edge(i) + 1.0


def _t_before(i):
    """第 i 个 tick 更新之前（此时相号 = i%4，读列驱动用）。"""
    return TICK_PERIOD * i + CLK_PERIOD / 2.0


def _hex(v, width):
    return "X" if v is None else ("0x%0*X" % (width, v))


def _bin4(v):
    return "X" if v is None else format(v & 0xF, "04b")


def _pulses(vf, name="o_key_press"):
    """把某单比特信号的高电平段拆成 [(起, 止), ...]。"""
    tr = vf.trace(name)
    out = []
    for i, (t, lv) in enumerate(tr):
        if lv == "1":
            end = tr[i + 1][0] if i + 1 < len(tr) else DURATION
            out.append((t, end))
    return out


def _in_win(pulses, t0, t1):
    return [p for p in pulses if t0 <= p[0] < t1]


# ============================================================
# 5. 断言
# ============================================================
def check(vf):
    res = []
    pulses = _pulses(vf)

    # ---- ① 列驱动极性：每个相恰好一位 = ACTIVE、位号 = 相号 ----
    bad_col, seen = [], {}
    for i in range(N):
        want = _colpat(i % 4)
        got = vf.bus_value_at("o_kp_col", _t_before(i))
        seen.setdefault(i % 4, got)
        if got != want:
            bad_col.append("tick %d(相%d): o_kp_col=%s 期望 %s"
                           % (i, i % 4, _bin4(got), _bin4(want)))
    res.append((
        "① 列驱动极性：每个相恰好选中一列（驱 '%d'）、其余驱 '%d'、位号 = 相号"
        % (ACTIVE, 1 - ACTIVE),
        not bad_col,
        ("%s：" % POLARITY)
        + "；".join("相%d=%s" % (p, _bin4(seen.get(p))) for p in range(4))
        + ("" if not bad_col else "\n" + "\n".join(bad_col[:6])),
    ))

    # ---- ② 无键不误报（Phase A）—— 与**文档预测**比对 ----
    nA = 4 * PHASE_ROUNDS
    codes_A = [vf.bus_value_at("o_key_code", _t_after(i)) for i in range(nA)]
    bad_idle = [i for i in range(nA) if codes_A[i] != 0]
    p_A = _in_win(pulses, 0.0, TICK_PERIOD * nA)
    measured = bool(bad_idle) or bool(p_A)
    phantom = codes_A[bad_idle[0]] if bad_idle else None
    res.append((
        "② 无键不误报（文档预测：%s）—— %d 轮行全为板子空闲电平"
        % ("会误报" if DOC_EXPECT_FALSE_REPORT else "不得误报", PHASE_ROUNDS),
        measured == DOC_EXPECT_FALSE_REPORT,
        "实测：%s；o_key_code 非 0 次数 = %d；首个非 0 键号 = %s；Phase A 脉冲数 = %d。"
        "（板型判定规则『行空闲电平 == 按下电平 ⇒ 必误报』预测 = %s）"
        % ("误报" if measured else "不误报", len(bad_idle), _hex(phantom, 2),
           len(p_A), "误报" if PHYSICS_FALSE_REPORT else "不误报"),
    ))

    if MATCHED:
        # ============ 匹配板（格 1/4）：测真实按键 ============
        # ---- ③ 键号：第 1 个轮末 code = 2，按住期间恒 2 ----
        code_r1 = vf.bus_value_at("o_key_code", _t_after(I_B_R1END))
        bad_hold = [i for i in range(I_B_R1END, I_B0 + 4 * PHASE_ROUNDS)
                    if vf.bus_value_at("o_key_code", _t_after(i)) != 2]
        res.append((
            "③ 真实按键：按住 KEY2（ROW3/COL1）→ 第 1 个轮末 o_key_code = 2，按住期间恒 2",
            code_r1 == 2 and not bad_hold,
            "%s：行读到 '%d' = 按下；第 1 个轮末 o_key_code=%s（期望 2）；按住期偏离次数 = %d"
            % (POLARITY, ACTIVE, _hex(code_r1, 2), len(bad_hold)),
        ))

        # ---- ④ 消抖时长：恰 1 个脉冲，落在第 21 个轮末、距按下沿 80~87ms ----
        t_B0 = _t_edge(I_B0)
        t_B1 = _t_edge(I_B0 + 4 * PHASE_ROUNDS - 1) + 1.0
        p_B = _in_win(pulses, t_B0, t_B1)
        onset = TICK_PERIOD * I_B0
        real_ms = ((p_B[0][0] - onset) / TICK_PERIOD * TICK_REAL_MS) if p_B else -1.0
        res.append((
            "④ 消抖时长：o_key_press 恰 1 个脉冲，上升沿落在第 21 个轮末、距按下沿 80~87ms",
            len(p_B) == 1 and abs(p_B[0][0] - _t_edge(I_B_PULSE)) < 1.0
            and 80.0 <= real_ms <= 87.0,
            "Phase B 脉冲数 = %d；脉冲沿 = %s（期望 %.0f ns）；距按下沿 %.2f ms"
            % (len(p_B), ("%.0f" % p_B[0][0]) if p_B else "—",
               _t_edge(I_B_PULSE), real_ms),
        ))

        # ---- ⑤ 脉冲宽度 = 恰好 1 个 clk ----
        widths = [(p[1] - p[0]) / CLK_PERIOD for p in p_B]
        res.append((
            "⑤ 脉冲宽度契约（CLAUDE.md §10.1）：每个 o_key_press 高电平恰好 1 个 clk",
            len(p_B) > 0 and all(abs(w - 1.0) < 1e-6 for w in widths),
            "Phase B 脉冲宽度（clk 拍数）：%s" % ["%.3g" % w for w in widths],
        ))

        # ---- ⑥ 松开后归零、无新脉冲 ----
        p_C = _in_win(pulses, _t_edge(I_C0), DURATION)
        bad_c = [i for i in range(I_C0 + 3, I_END)
                 if vf.bus_value_at("o_key_code", _t_after(i)) != 0]
        res.append((
            "⑥ 松开后 o_key_code 归 0、无新脉冲",
            not p_C and not bad_c,
            "Phase C 脉冲数 = %d；o_key_code 非 0 次数 = %d" % (len(p_C), len(bad_c)),
        ))
    else:
        # ============ 失配板（格 2/3）：断言误报**必然发生** ============
        # ---- ③ 幻影键号：整段无键（含"按键"阶段）都持续误报同一键 ----
        codes_all = [vf.bus_value_at("o_key_code", _t_after(i)) for i in range(N)]
        nz = [c for c in codes_all if c != 0]
        phantom_keys = sorted(set(nz))
        res.append((
            "③ ⭐ ERR-0035 复现：无键起 o_key_code 持续非 0，幻影键号 = 4（「开始」）",
            bool(nz) and phantom_keys == [4] and codes_all[3] == 4,
            "实测幻影键号集合 = %s；非 0 次数 = %d/%d；首个非 0 = %s（第 1 个轮末即锁存 4）"
            % (phantom_keys, len(nz), len(codes_all),
               _hex(codes_all[bad_idle[0]], 2) if bad_idle else "—"),
        ))

        # ---- ④ 误报时 o_key_press 的行为（**全程**统计个数 / 时刻 / 宽度）----
        p_all = _in_win(pulses, 0.0, DURATION)
        widths = [(p[1] - p[0]) / CLK_PERIOD for p in p_all]
        res.append((
            "④ 误报时 o_key_press 的行为：全程脉冲个数 / 时刻 / 宽度（单周期脉冲）",
            len(p_all) >= 1 and all(abs(w - 1.0) < 1e-6 for w in widths),
            "全程脉冲数 = %d（Phase A 内 %d 个）；时刻 = %s ns；宽度（clk 拍数）= %s"
            % (len(p_all), len(p_A), ["%.0f" % p[0] for p in p_all],
               ["%.3g" % w for w in widths]),
        ))

    return res

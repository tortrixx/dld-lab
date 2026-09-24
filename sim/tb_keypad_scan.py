# -*- coding: utf-8 -*-
"""tb_keypad_scan.py —— keypad_scan（4×4 矩阵键盘扫描与消抖）的功能仿真激励与断言

【为什么本模块是"本轮最需要盯的"】
    2026-09-24 上板时键盘**一直误报「开始」键被按下**，把整机踢出自检态
    （现场表现："没有 2 秒自检、直接 5 秒计时"）。根因是**扫描极性选反了**：
    原按开发板手册写成高有效（行读到 '1' = 按下），而实测行在**无按键时就一直读到 '1'**
    → 每一相都误报 → 幻影键号随相号循环 1→2→3→4，整轮锁存的恰好是 **4 =「开始」**。
    详见 `ERRORS.md` **ERR-0035** / `docs/04` §3.3。

    修复方案是新增**全项目唯一的极性翻转点**常量：
        `constant KP_ACTIVE : std_logic := '0';`   -- '0' = 低有效（当前默认）
    列驱动与行判定都跟着它走。**所以本 tb 必须把两种取值都跑一遍。**

【⭐ 两条不可省的断言（就是今天事故的两条回归）】
    ① **两种极性都测**：`KP_ACTIVE` = '0'（低有效，默认）与 '1'（高有效，RTL_PATCHES 翻转）
       各跑一轮。断言"**列驱动与行判定同时翻转**"：
         · 低有效：选中列驱 '0'、其余驱 '1'；按下时该行读到 '0'。
         · 高有效：选中列驱 '1'、其余驱 '0'；按下时该行读到 '1'。
       只测一种极性等于没测 —— 今天的事故就是这么漏掉的。
    ② **无按键不得误报**：所有行驱动为"未按下"电平、持续 ≥ 21 个扫描轮
       （= 消抖时长，足以让任何幻影键出脉冲）后，断言 `o_key_code == 0`
       且 `o_key_press` **始终为 0**。这正是 ERR-0035 的回归测试。

【本 tb 的极性开关】
    文件顶部的 `KP_ACTIVE`（0/1）同时决定：① 驱动行时"按下"用哪个电平；
    ② `RTL_PATCHES` 是否把 RTL 的常量翻转。**两边必须一起改** —— 这正是"同时翻转"的含义：
    若只有列驱动翻转、行判定没翻转（或反之），键号就会错、或出现幻影键，
    下面的断言会立刻抓到。

【模块行为（`docs/02` §4.4）】
    · 扫描相：4 个 `i_tick` 一轮（一轮 = 4ms）。相 p 选中第 p 列。
    · 消抖单位是"**轮**"而不是"相"：必须先把 4 相锁存成"轮键号"，整轮末才判定
      （若按相判定，无键相会把计数器清零 → 消抖永远完不成，是 P0 缺陷）。
    · 时长账：第 1 个轮末建立 `r_stable`（不计）、随后 19 个轮末累加、
      **第 21 个轮末**才出 `o_key_press` → 距按下沿 **80~87ms**（VP6）。
    · `o_key_press` 是**单周期脉冲（宽 1 个 clk）**（VP7，跨模块契约 `CLAUDE.md` §10.1）。
    · 键号公式 `KEY号 = (3-ROW)*4 + COL + 1`；`o_key_code` 是 **5 位**（最大 16）。

【激励时间线】（单位 ns；clk 20ns、i_tick 每 40ns 一拍；本 tb 直接驱动 i_tick，不改 CLK_HZ）
    A  无键        25 轮（100 tick）   → VP1（无键不误报，ERR-0035 回归）
    B  按住 KEY2  250 轮（1000 tick）  → VP2/5/6/7（长按 1 秒，只出 1 个脉冲，第 21 轮末）
    G1 松开        25 轮（100 tick）   → 闸门 r_down 重新开门
    J  抖动+稳定   5 轮抖动 + 25 轮稳定 → VP3（抖动只出 1 个脉冲）
    G2 松开        25 轮（100 tick）
    T  遍历 16 键  16×2 轮（128 tick） → VP4（键号 1..16 与公式一致）
    尾 无键        5 轮（20 tick）
    合计 392 轮 = 1568 tick = 62.72µs 仿真时间。
"""

# ============================================================
# ★ 极性开关：0 = 低有效（当前 RTL 默认）；1 = 高有效（RTL_PATCHES 翻转常量）
#   两种取值各跑一轮 —— 见文件头 ⭐ ①
# ============================================================
KP_ACTIVE = 0

if KP_ACTIVE == 1:
    RTL_PATCHES = [
        ("rtl/keypad_scan.vhd",
         "constant KP_ACTIVE : std_logic := '0';",
         "constant KP_ACTIVE : std_logic := '1';"),
    ]
else:
    RTL_PATCHES = []

ACTIVE   = KP_ACTIVE        # 该电平 = "按下"，同时 = 选中列的驱动电平
IDLE     = 1 - KP_ACTIVE    # 未按下 / 未选中列
POLARITY = "高有效" if KP_ACTIVE == 1 else "低有效"

# ============================================================
# 时序常量（本模块只用 i_tick，tb 直接驱动，无需 CLK_HZ 缩放）
# ============================================================
CLK_PERIOD  = 20.0          # 50MHz 等价
TICK_PERIOD = 40.0          # i_tick 每 2 个 clk 来一拍（模块内每拍推进一步相）
TICK_REAL_MS = 1.0          # 一个 i_tick = 1ms（真实时间，用于把仿真时长折回 ms）

# ============================================================
# 激励块（单位：轮；一轮 = 4 个 i_tick）
# ============================================================
IDLE_A   = 25               # 无键（≥21 轮，足够让幻影键出脉冲）
PRESS_B  = 250              # 按住 KEY2 = 1 秒（250 轮 × 4ms）
GAP1     = 25
JIT_ALT  = [2, 3, 2, 3, 2]  # 抖动：逐轮在 KEY2/KEY3 之间跳
JIT_HOLD = 25               # 抖动后稳定按住 KEY2
GAP2     = 25
TRAV_PER = 2                # 每个键按住 2 轮（足够让 r_stable 建立）
TAIL     = 5

# ---- 逐 tick 的"当前按住的键"（0 = 无键）----
TICKS = []
TICKS += [0] * (4 * IDLE_A)
TICKS += [2] * (4 * PRESS_B)
TICKS += [0] * (4 * GAP1)
for _k in JIT_ALT:
    TICKS += [_k] * 4
TICKS += [2] * (4 * JIT_HOLD)
TICKS += [0] * (4 * GAP2)
for _key in range(1, 17):
    TICKS += [_key] * (4 * TRAV_PER)
TICKS += [0] * (4 * TAIL)
N = len(TICKS)

DURATION    = N * TICK_PERIOD
GRID_PERIOD = TICK_PERIOD

# ---- 各块的 tick 边界（0 基 tick 下标）----
I_A0  = 0
I_B0  = I_A0 + 4 * IDLE_A                      # 100
I_G1  = I_B0 + 4 * PRESS_B                     # 1100
I_J0  = I_G1 + 4 * GAP1                        # 1200
I_G2  = I_J0 + 4 * len(JIT_ALT) + 4 * JIT_HOLD  # 1320
I_TR  = I_G2 + 4 * GAP2                        # 1420
I_TAIL = I_TR + 4 * TRAV_PER * 16              # 1548

# ---- 关键期望时刻（tick 下标）----
# PRESS_B：按下从 tick I_B0 起（第 1 轮 = I_B0..I_B0+3）。
# 第 1 个轮末建立 r_stable（tick I_B0+3）；第 21 个轮末出脉冲（tick I_B0+83）。
I_B_R1END = I_B0 + 3                            # 第 1 个轮末
I_B_PULSE = I_B0 + 83                           # 第 21 个轮末
# 抖动：第 5 轮末建立 KEY2（tick I_J0+19），第 25 轮末出脉冲（tick I_J0+99）。
I_J_LASTCHG = I_J0 + 4 * len(JIT_ALT) - 1       # 最后一次抖动轮末
I_J_PULSE   = I_J0 + 4 * (len(JIT_ALT) + 20) - 1  # +20 轮


# ============================================================
# 参考模型：按"当前相 + 当前按住的键"算出 i_kp_row 该是什么电平
#   键号公式 KEY号 = (3-ROW)*4 + COL + 1  ⇒  COL = (KEY-1)%4、ROW = 3-(KEY-1)//4
#   按下时该键把"选中列"的驱动电平接到行上 → 行读到 ACTIVE
# ============================================================
def _key_row_col(key):
    return (3 - (key - 1) // 4, (key - 1) % 4)      # (ROW, COL)


def _rowval(key, phase):
    """第 `phase` 相扫描时，行输入应为的电平（4 位整数）。"""
    val = 0
    for r in range(4):
        b = IDLE
        if key != 0:
            krow, kcol = _key_row_col(key)
            if r == krow and phase == kcol:
                b = ACTIVE
        val |= b << r
    return val


def _colpat(phase):
    """列驱动参考模型：恰好第 `phase` 位 = ACTIVE，其余 = IDLE。"""
    return sum((ACTIVE if b == phase else IDLE) << b for b in range(4))


# ============================================================
# 观测点（中间信号缺失即报错，docs/03 §3.1 第 5 条）
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

    # 中间信号：声明为输出（不由 tb 驱动）→ 由仿真回写；名字不在网表里就查不到波形
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
# 采样辅助
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
# 断言
# ============================================================
def check(vf):
    res = []
    pulses = _pulses(vf)

    # ---- ① 列扫描极性：每个相恰好一位 = ACTIVE、位号 = 相号 ----
    bad_col = []
    seen = {}
    for i in range(N):
        want = _colpat(i % 4)
        got = vf.bus_value_at("o_kp_col", _t_before(i))
        seen.setdefault(i % 4, got)
        if got != want:
            bad_col.append("tick %d(相%d): o_kp_col=%s 期望 %s"
                           % (i, i % 4, _bin4(got), _bin4(want)))
    res.append((
        "① 列扫描极性：每个相恰好选中一列（一位为有效电平）、位号 = 相号",
        not bad_col,
        ("%s：选中列驱 '%d'、其余驱 '%d'；" % (POLARITY, ACTIVE, IDLE))
        + "；".join("相%d=%s" % (p, _bin4(seen.get(p))) for p in range(4))
        + ("" if not bad_col else "\n" + "\n".join(bad_col[:6])),
    ))

    # ---- ② 行判定极性：按下 KEY2（ROW3/COL1）→ 第 1 个轮末 o_key_code = 2 ----
    code_r1 = vf.bus_value_at("o_key_code", _t_after(I_B_R1END))
    res.append((
        "② 行判定极性：按住 KEY2（ROW3/COL1）→ 第 1 个轮末 o_key_code = 2",
        code_r1 == 2,
        "%s：行读到 '%d' = 按下；实测 o_key_code=%s（期望 2）。"
        "若两种极性里这一条都过、而 ① 的极性确实相反，即「列驱动与行判定同时翻转」"
        % (POLARITY, ACTIVE, _hex(code_r1, 2)),
    ))

    # ---- ③ 无键不误报（ERR-0035 回归）----
    t_A_end = TICK_PERIOD * (4 * IDLE_A)
    bad_idle = []
    for i in range(0, 4 * IDLE_A):
        c = vf.bus_value_at("o_key_code", _t_after(i))
        if c != 0:
            bad_idle.append("tick %d: o_key_code=%s" % (i, _hex(c, 2)))
    p_A = _in_win(pulses, 0.0, t_A_end)
    res.append((
        "③ ⭐ 无键不误报（ERR-0035 回归）：%d 轮（= %d tick，≥ 21 轮消抖时长）行全为未按下电平，"
        "o_key_code 恒 0 且 o_key_press 恒 0" % (IDLE_A, 4 * IDLE_A),
        not bad_idle and not p_A,
        "无键窗口内 o_key_press 脉冲数 = %d；o_key_code 非 0 次数 = %d"
        % (len(p_A), len(bad_idle)),
    ))

    # ---- ④ 消抖"前 vs 后"：轮末先建立键号，第 21 个轮末才出脉冲 ----
    t_B0, t_B1 = _t_edge(I_B0), _t_edge(I_B0 + 4 * PRESS_B - 1) + 1.0
    bad_pre = []
    for i in range(I_B_R1END, I_B_PULSE):           # 第 1~20 个轮末之间
        c = vf.bus_value_at("o_key_code", _t_after(i))
        p = vf.value_at("o_key_press", _t_after(i))
        if c != 2 or p != "0":
            bad_pre.append("tick %d: code=%s press=%s" % (i, _hex(c, 2), p))
    p_B = _in_win(pulses, t_B0, t_B1)
    res.append((
        "④ 消抖前后差异：第 1 个轮末 o_key_code 即 = 2（已锁存「轮键号」），"
        "但 o_key_press 直到第 21 个轮末才出",
        (not bad_pre) and len(p_B) == 1
        and abs(p_B[0][0] - _t_edge(I_B_PULSE)) < 1.0,
        "第 1~20 个轮末异常数 = %d；PRESS_B 内脉冲数 = %d，脉冲时刻 = %s（期望 %.0f ns）"
        % (len(bad_pre), len(p_B), ("%.0f" % p_B[0][0]) if p_B else "—",
           _t_edge(I_B_PULSE)),
    ))

    # ---- ⑤ 脉冲宽度 = 恰好 1 个 clk ----
    widths = [(p[1] - p[0]) / CLK_PERIOD for p in pulses]
    res.append((
        "⑤ 脉冲宽度契约（CLAUDE.md §10.1）：每个 o_key_press 高电平恰好 1 个 clk",
        all(abs(w - 1.0) < 1e-6 for w in widths),
        "各脉冲宽度（clk 拍数）：%s" % ["%.3g" % w for w in widths],
    ))

    # ---- ⑥ 长按 1 秒：o_key_code 恒为 2、o_key_press 只有 1 个脉冲 ----
    bad_hold = [i for i in range(I_B_R1END, I_B0 + 4 * PRESS_B)
                if vf.bus_value_at("o_key_code", _t_after(i)) != 2]
    res.append((
        "⑥ 长按 1 秒（%d 轮）：按住期间 o_key_code 恒 = 2，o_key_press 只出 1 个脉冲"
        % PRESS_B,
        not bad_hold and len(p_B) == 1,
        "键号偏离次数 = %d；脉冲数 = %d" % (len(bad_hold), len(p_B)),
    ))

    # ---- ⑦ 抖动只出 1 个脉冲（消抖生效）----
    t_J0 = _t_edge(I_J0)
    t_J1 = _t_edge(I_J0 + 4 * (len(JIT_ALT) + JIT_HOLD) - 1) + 1.0
    p_J = _in_win(pulses, t_J0, t_J1)
    ok_J = (len(p_J) == 1
            and abs(p_J[0][0] - _t_edge(I_J_PULSE)) < 1.0
            and p_J[0][0] >= _t_edge(I_J_LASTCHG) + 19 * TICK_PERIOD - 1.0)
    res.append((
        "⑦ 抖动（%d 轮 KEY2/KEY3 逐轮跳 + %d 轮稳定）→ o_key_press 只出 1 个脉冲，"
        "且在最后一次变化后 ≥ 19 轮才出现" % (len(JIT_ALT), JIT_HOLD),
        ok_J,
        "抖动窗口脉冲数 = %d；脉冲时刻 = %s（期望 %.0f ns）；最后一次变化时刻 = %.0f ns"
        % (len(p_J), ("%.0f" % p_J[0][0]) if p_J else "—", _t_edge(I_J_PULSE),
           _t_edge(I_J_LASTCHG)),
    ))

    # ---- ⑧ 遍历 16 键：键号 1..16 与公式一致 ----
    got_keys, bad_trav = [], []
    for j in range(16):
        key = j + 1
        i_end = I_TR + 8 * j + 7                     # 每个键的第 2 个轮末
        c = vf.bus_value_at("o_key_code", _t_after(i_end))
        got_keys.append(c)
        if c != key:
            krow, kcol = _key_row_col(key)
            bad_trav.append("KEY%d(ROW%d/COL%d): 实测 %s 期望 %d"
                            % (key, krow, kcol, _hex(c, 2), key))
    res.append((
        "⑧ 遍历 16 键：o_key_code 依次 = 1..16，与 KEY号 = (3-ROW)*4+COL+1 一致",
        not bad_trav,
        ("实测键号序列 = %s" % got_keys) if not bad_trav
        else "\n".join(bad_trav),
    ))

    # ---- ⑨ 距按下沿 80~87ms（VP6）----
    if p_B:
        onset_ns = TICK_PERIOD * I_B0
        real_ms = (p_B[0][0] - onset_ns) / TICK_PERIOD * TICK_REAL_MS
        ok9 = 80.0 <= real_ms <= 87.0
        detail = ("按下沿 = %.0f ns、脉冲沿 = %.0f ns、差 %.0f tick → 折算真实 %.2f ms"
                  "（期望 80~87ms）" % (onset_ns, p_B[0][0],
                                        (p_B[0][0] - onset_ns) / TICK_PERIOD, real_ms))
    else:
        ok9, detail = False, "没有测到脉冲，无法判定"
    res.append(("⑨ 消抖时长：脉冲沿距按下沿落在 80~87ms（第 21 个轮末）", ok9, detail))

    # ---- ⑩ 全程脉冲总数（无键/松开期不得出脉冲）----
    t_G1a, t_G1b = _t_edge(I_G1), _t_edge(I_J0 - 1) + 1.0
    t_G2a, t_G2b = _t_edge(I_G2), _t_edge(I_TR - 1) + 1.0
    t_Ta,  t_Tb  = _t_edge(I_TR), _t_edge(I_TAIL - 1) + 1.0
    bad_gap = []
    for (nm, a, b) in (("G1", t_G1a, t_G1b), ("G2", t_G2a, t_G2b), ("T", t_Ta, t_Tb)):
        if _in_win(pulses, a, b):
            bad_gap.append(nm)
    for (nm, a, b) in (("G1", I_G1, I_J0), ("G2", I_G2, I_TR)):
        for i in range(a + 3, b):
            if vf.bus_value_at("o_key_code", _t_after(i)) != 0:
                bad_gap.append("%s@tick%d" % (nm, i))
    res.append((
        "⑩ 全程脉冲总数 = 2（长按 1 个 + 抖动 1 个）；松开/遍历期无脉冲、o_key_code = 0",
        len(pulses) == 2 and not bad_gap,
        "全程脉冲 %d 个：%s；异常 = %s"
        % (len(pulses), ["%.0f" % p[0] for p in pulses], bad_gap or "无"),
    ))

    return res

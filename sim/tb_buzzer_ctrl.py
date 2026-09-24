# -*- coding: utf-8 -*-
"""tb_buzzer_ctrl.py —— buzzer_ctrl 的功能仿真激励与断言

【本模块要回答什么】
    `buzzer_ctrl`（S7 音效输出）以 `i_tick_8k` 为半周期时基，对 `o_buzz` 输出方波，
    8 种音效各有 (频率, 时长)。本 tb 钉四件事：

      ① **方波频率**：逐个测出实际半周期（拍数），与 `docs/02` §13.3 查表的目标频率比对；
      ② ⭐ **ERR-0016 的 off-by-one**：查表存 N-1、计数器从 N-1 数到 0 共 **N 拍** ——
         实测半周期必须**恰为 N 拍**（不是 N+1 拍）。当年就是"装载 N 得 N+1 拍"、频率全错；
      ③ **`i_trigger` 两个方向**：单个 1 拍脉冲触发一次完整播放；按住不放**不重复触发**
         （实测为静音 —— 实现是"电平装载、非边沿检测"，见 `docs/02` §13.5 的既定契约）；
      ④ **静音电平**：未触发 / 每种音效播完后 `o_buzz` 恒 '0'；`i_sound_sel=0` 恒静音。

【独立来源，不自证】
    期望值来自 `docs/02` §13.3 的**查表**（半周期 N 与时长拍数），
    **绝不从 `rtl/buzzer_ctrl.vhd` 抄常量** —— 否则 RTL 错、tb 也跟着错
    （`docs/07` §2 第 5 条 / 任务要求"不许自证"）。

【时间模型】（clk 20ns；i_tick_8k 周期 40ns、高 1 个 clk）
    tick 采样沿 = clk 上升沿且 i_tick_8k=1 → t = 30 + 40·j。
    触发脉冲做成"高 1 个 clk"、正好覆盖某个 tick 采样沿 → 触发那一拍装载，
    之后第 k 拍出现在 T + 40k（**这是实测半周期拍数的量尺**）。
    ⚠️ 时序模块必须显式给复位：综合后网表寄存器初值是 X，不是 0。

【中间信号】（课件 p59 / `docs/03` §3.1）—— 波形里必须有中间信号
    综合后网表里内部寄存器必须声明为 **BURIED**（写成 OUTPUT 会报
    `Wrong node type ... Design node is of type Buried`，见 `tb_clk_gen.py`）。
    本 tb 收录 `r_play`（锁存的音效号）/ `r_alt`（交替相位）/ `r_buzz`（方波内部寄存器）/
    `r_half`（半周期计数器 —— ERR-0016 的主角）。
    ⚠️ `r_dur` / `r_seg` 每拍都变、10 万+ 跳变，会把回写 `.vwf` 撑到 MB 级，
       其正确性已由 `o_buzz` 的时长/段结构断言逐条覆盖，故不放进波形。
"""

# ============================================================
# 时间参数
# ============================================================
DURATION = 435000.0         # 435 us（压缩时间：1 拍 = 40ns）
GRID_PERIOD = 10.0
CLK_PERIOD = 20.0           # clk 周期
TICK_PERIOD = 40.0          # i_tick_8k 周期（低 1 拍、高 1 拍）
TICK_EDGE0 = 30.0           # 第一个 tick 采样沿（clk 上升沿）
GAP = 10                    # 相邻测试之间的空档（拍）
HOLD_TICKS = 300            # "按住不放"持续的拍数
HOLD_SEL = 1                # "按住不放"用的音效号


def t_of_tick(j):
    """第 j 个 tick 采样沿的时刻（ns）。"""
    return TICK_EDGE0 + TICK_PERIOD * j


# ============================================================
# 音效表 —— ★ 独立来源：docs/02 §13.3 的查表（不是从 rtl 抄）
#   n   = 半周期（拍），交替音为 (A 段, B 段)
#   dur = 总时长（拍）
#   seg = 交替段长（拍），0 = 单音
#   频率 = 8000 / (2n) = 4000 / n  Hz
# ============================================================
SOUND = {
    0: {"n": None,    "dur": 0,    "seg": 0},
    1: {"n": 2,       "dur": 240,  "seg": 0},
    2: {"n": 4,       "dur": 160,  "seg": 0},
    3: {"n": 8,       "dur": 640,  "seg": 0},
    4: {"n": 4,       "dur": 400,  "seg": 0},
    5: {"n": 1,       "dur": 480,  "seg": 0},
    6: {"n": (2, 1),  "dur": 3200, "seg": 800},
    7: {"n": (8, 16), "dur": 4800, "seg": 1200},
}


# ============================================================
# 时间线（拍号 j → 时刻）
#   singles : sel 1..7、sel 0 各一个 1 拍触发脉冲
#   dbl     : 双触发（sel3 播到第 100 拍时被 sel2 打断）
#   hold    : 按住不放 300 拍，之后释放
# ============================================================
def _mk_schedule():
    singles = []
    j = 1
    for sel in (1, 2, 3, 4, 5, 6, 7):
        singles.append((t_of_tick(j), sel))
        j += SOUND[sel]["dur"] + GAP
    singles.append((t_of_tick(j), 0))      # sel 0（静音）
    j += 40                                # 静音档要多留观察窗（GAP=10 不够 20 拍）
    dbl_a_j = j
    dbl_b_j = j + 100                      # 第二个脉冲：第一个播放中途
    j = dbl_b_j + SOUND[2]["dur"] + GAP
    hold_j = j
    hold_end_j = j + HOLD_TICKS
    return singles, dbl_a_j, dbl_b_j, hold_j, hold_end_j


SINGLES, DBL_A_J, DBL_B_J, HOLD_J, HOLD_END_J = _mk_schedule()
T_DBL_A = t_of_tick(DBL_A_J)
T_DBL_B = t_of_tick(DBL_B_J)
T_HOLD = t_of_tick(HOLD_J)
T_HOLD_END = t_of_tick(HOLD_END_J)


# ============================================================
# 端口 / 中间信号
# ============================================================
PORTS_OUT = ["o_buzz"]

# 中间信号：名字 -> 位宽（1 = 单比特）。综合后网表里内部信号是 Buried。
BURIED = {
    "r_play": 3,     # 触发时锁存的音效号
    "r_alt": 1,      # 交替相位
    "r_buzz": 1,     # 方波内部寄存器
    "r_half": 4,     # 半周期计数器（ERR-0016 的主角）
}

OBSERVE = ["clk", "rst", "i_tick_8k", "i_sound_sel", "i_trigger"] + PORTS_OUT + list(BURIED.keys())


def _buried(b, name, width):
    """把节点（含其比特子节点）标成 BURIED —— 综合后网表里内部信号就是 Buried。"""
    for n in [name] + ["%s[%d]" % (name, i) for i in range(width)]:
        sig = b.vf.signals.get(n)
        if sig is not None:
            sig.direction = "BURIED"


def _decl(b, name, width):
    if width > 1:
        b.output_bus(name, width)
    else:
        b.output_bit(name)


def _trigger_windows():
    """i_trigger 的所有高电平窗口（每个窗口只覆盖一个 clk 上升沿 → 恰好 1 拍脉冲）。"""
    wins = []
    for (t, _sel) in SINGLES:
        wins.append((t - CLK_PERIOD / 2, t + CLK_PERIOD / 2))
    wins.append((T_DBL_A - CLK_PERIOD / 2, T_DBL_A + CLK_PERIOD / 2))
    wins.append((T_DBL_B - CLK_PERIOD / 2, T_DBL_B + CLK_PERIOD / 2))
    # 按住不放：高电平横跨 HOLD_TICKS 个 tick 采样沿，直到释放沿之前
    wins.append((T_HOLD - CLK_PERIOD / 2, T_HOLD_END - CLK_PERIOD / 2))
    wins.sort()
    return wins


def _segments_from_windows(wins):
    segs = []
    cur = 0.0
    for (a, b) in wins:
        if a > cur + 1e-9:
            segs.append((a - cur, 0))
        segs.append((b - a, 1))
        cur = b
    segs.append((DURATION - cur, 0))
    return segs


def _sel_segments():
    """i_sound_sel：每个触发前沿 10ns 切到该测试的音效号（触发拍锁存，之后可随意变）。"""
    entries = [(t, s) for (t, s) in SINGLES] + \
              [(T_DBL_A, 3), (T_DBL_B, 2), (T_HOLD, HOLD_SEL)]
    entries.sort()
    segs = []
    cur = 0.0
    val = 0
    for (t, s) in entries:
        a = t - CLK_PERIOD / 2
        if a > cur + 1e-9:
            segs.append((a - cur, val))
            cur = a
        val = s
    segs.append((DURATION - cur, val))
    return segs


def build(b):
    b.input_bit("clk")
    b.input_bit("rst")
    b.input_bit("i_tick_8k")
    b.input_bus("i_sound_sel", 3)
    b.input_bit("i_trigger")
    for n in PORTS_OUT:
        b.output_bit(n)
    for n, w in BURIED.items():
        _decl(b, n, w)
        _buried(b, n, w)

    b.clock("clk", CLK_PERIOD)
    # ⚠️ i_tick_8k 直接用 clock 生成（低 1 拍 / 高 1 拍）→ 用嵌套 REPEAT 压缩，
    #    否则 1 万多个 tick 会写出 2 万行 LEVEL。
    b.clock("i_tick_8k", TICK_PERIOD)
    # ⚠️ 时序模块必须显式复位（综合后网表寄存器初值是 X）
    b.segments("rst", [(40.0, 1), (DURATION - 40.0, 0)])
    b.segments("i_trigger", _segments_from_windows(_trigger_windows()))
    b.bus_segments("i_sound_sel", _sel_segments())


# ============================================================
# 辅助
# ============================================================
def _edges(vf, t0, t1, name="o_buzz"):
    """name 在 (t0, t1] 内的电平跳变 [(时刻, 跳变后电平), ...]。"""
    return [(t, lv) for (t, lv) in vf.trace(name) if t0 + 1e-6 < t <= t1 + 1e-6]


def _ticks(dt):
    return int(round(dt / TICK_PERIOD))


def _trig_of(sel):
    for (t, s) in SINGLES:
        if s == sel:
            return t
    return None


# ============================================================
# 断言
# ============================================================
def check(vf):
    res = []

    def lv(t, name="o_buzz"):
        return vf.value_at(name, t)

    # ---- ① 中间信号确实有波形（课件 p59 / docs/03 §3.1 第 5 条）----
    missing = []
    for n, w in BURIED.items():
        if w > 1:
            if not any(vf.trace("%s[%d]" % (n, i)) for i in range(w)):
                missing.append(n)
        elif not vf.trace(n):
            missing.append(n)
    res.append((
        "① 中间信号全部有波形（%s）" % "、".join(BURIED),
        not missing,
        "缺失：%s" % missing if missing else "全部有 TRANSITION_LIST",
    ))

    # ---- ② 静音电平：未触发 / 播完后 o_buzz 恒 '0'（两个方向都测）----
    quiet = [("复位后、首次触发前", 60.0)]
    for i, (t, sel) in enumerate(SINGLES):
        end = t + SOUND[sel]["dur"] * TICK_PERIOD
        nxt = SINGLES[i + 1][0] if i + 1 < len(SINGLES) else T_DBL_A
        if nxt - end > 3 * TICK_PERIOD:
            quiet.append(("sel=%d 播完后 +1 拍" % sel, end + TICK_PERIOD))
            quiet.append(("sel=%d 播完后（近下一触发）" % sel, nxt - 2 * TICK_PERIOD))
    quiet.append(("双触发播完后", T_DBL_B + SOUND[2]["dur"] * TICK_PERIOD + 2 * TICK_PERIOD))
    bad = [(lbl, t, lv(t)) for (lbl, t) in quiet if lv(t) != "0"]
    res.append((
        "② 静音电平：未触发 / 每种音效播完后 o_buzz 恒 '0'（%d 个采样点）" % len(quiet),
        not bad,
        "全部为 '0'" if not bad else "非 '0' 的采样点：%s" % bad,
    ))

    # ---- ③ sel=0（静音档）→ 触发后恒静音 ----
    t0 = _trig_of(0)
    ed0 = _edges(vf, t0, t0 + 20 * TICK_PERIOD)
    res.append((
        "③ i_sound_sel=0（静音档）：给触发脉冲后 o_buzz 全程无翻转（恒 '0'）",
        len(ed0) == 0,
        "触发于 %.0f ns；其后 20 拍内翻转次数 = %d（应 0）" % (t0, len(ed0)),
    ))

    # ---- ④ 单音 1~5 的频率（实测半周期拍数 vs §13.3 查表 N）----
    rows = []          # (sel, N, 实测半周期拍, 实测频率 Hz, dur)
    bad4 = []
    for sel in (1, 2, 3, 4, 5):
        t = _trig_of(sel)
        n = SOUND[sel]["n"]
        dur = SOUND[sel]["dur"]
        ed = _edges(vf, t, t + dur * TICK_PERIOD + 0.5 * TICK_PERIOD)
        ts = [x[0] for x in ed]
        ivals = [_ticks(ts[i + 1] - ts[i]) for i in range(len(ts) - 1)]
        mn = ivals[0] if ivals else None
        f = (4000.0 / mn) if mn else None
        rows.append((sel, n, mn, f, dur))
        if mn is None or abs(mn - n) > 1:          # ±1 拍容差
            bad4.append(sel)
    res.append((
        "④ 单音 1~5 方波频率：实测半周期与 §13.3 查表 N 一致（±1 拍内）",
        not bad4,
        "; ".join("sel%d: 半周期实测 %s 拍（目标 N=%d）→ f≈%s Hz" %
                  (s, m, n, ("%.0f" % f) if f else "?") for (s, n, m, f, _d) in rows),
    ))

    # ---- ⑤ ⭐ ERR-0016 回归：实测半周期必须恰为 N 拍（不是 N+1）----
    strict_bad = [(s, m, n) for (s, n, m, _f, _d) in rows if m != n]
    res.append((
        "⭐ ⑤ ERR-0016 回归（off-by-one）：查表存 N-1、计数器数到 0 共 N 拍 → "
        "实测半周期必须**恰为 N 拍**（当年装载 N 得 N+1 拍、每种音效频率全错）",
        not strict_bad,
        "; ".join("sel%d: 查表 N-1=%d，实测相邻翻转间隔 = %d 拍 = N（%s）" %
                  (s, n - 1, m, "✓ 恰 N 拍，off-by-one 未复发" if m == n
                   else "✗ 偏 %+d 拍 —— off-by-one 复发！" % (m - n))
                  for (s, n, m, _f, _d) in rows),
    ))

    # ---- ⑥ 交替音 6/7 的段结构（§13.6-6）----
    alt_detail = []
    alt_bad = []
    for sel in (6, 7):
        t = _trig_of(sel)
        w = SOUND[sel]["seg"]
        na, nb = SOUND[sel]["n"]
        want = [w // na, w // nb, w // na, w // nb]
        got = [len(_edges(vf, t + k * w * TICK_PERIOD, t + (k + 1) * w * TICK_PERIOD))
               for k in range(4)]
        if got != want:
            alt_bad.append(sel)
        alt_detail.append("sel%d: 4 段（每段 %d 拍）翻转数 实测 %s / 目标 %s"
                          % (sel, w, got, want))
    res.append((
        "⑥ 交替音 6/7 的段结构：4 段窗口翻转数 = [400,800,400,800]（sel6，N=2↔1）/ "
        "[150,75,150,75]（sel7，N=8↔16）",
        not alt_bad,
        "\n".join(alt_detail),
    ))

    # ---- ⑦ 每种音效总时长（拍）与 §13.3 查表一致；播完自动静音 ----
    dur_rows = []
    dur_bad = []
    for sel in (0, 1, 2, 3, 4, 5, 6, 7):
        t = _trig_of(sel)
        dur = SOUND[sel]["dur"]
        if dur == 0:
            last = 0
        else:
            ed = _edges(vf, t, t + dur * TICK_PERIOD + 0.5 * TICK_PERIOD)
            last = _ticks(ed[-1][0] - t) if ed else None
        dur_rows.append((sel, dur, last))
        if last != dur:
            dur_bad.append(sel)
    res.append((
        "⑦ 每种音效的总时长（拍）与 §13.3 查表一致，播完自动静音",
        not dur_bad,
        "; ".join("sel%d: 实测 %s 拍 / 目标 %d 拍" % (s, m, d) for (s, d, m) in dur_rows),
    ))

    # ---- ⑧ 8 种音效（频率, 时长）两两不同 ----
    meas = {0: (("静音",), 0)}
    for (s, _n, _m, f, d) in rows:
        meas[s] = ((round(f),), d)
    for sel in (6, 7):
        t = _trig_of(sel)
        w = SOUND[sel]["seg"]
        c = [len(_edges(vf, t + k * w * TICK_PERIOD, t + (k + 1) * w * TICK_PERIOD))
             for k in range(4)]
        meas[sel] = ((round(4000.0 * c[0] / w), round(4000.0 * c[1] / w)),
                     SOUND[sel]["dur"])
    vals = list(meas.values())
    res.append((
        "⑧ 8 种音效（频率, 时长）两两不同（没有两种完全相同）",
        len(set(vals)) == len(vals),
        "; ".join("sel%d: %s Hz, %s 拍" %
                  (s, "/".join(str(x) for x in meas[s][0]), meas[s][1])
                  for s in range(8)),
    ))

    # ---- ⑨ i_trigger 方向一：单个 1 拍脉冲 → 恰好触发一次完整播放 ----
    t2 = _trig_of(2)
    ed2 = _edges(vf, t2, t2 + SOUND[2]["dur"] * TICK_PERIOD + 0.5 * TICK_PERIOD)
    n2 = len(ed2)
    res.append((
        "⑨ i_trigger 方向一：单个 1 拍脉冲 → 恰好触发一次完整播放"
        "（sel2：20ms 内 40 次翻转、时长 160 拍 —— §13.6-1/-2）",
        n2 == 40 and _ticks(ed2[-1][0] - t2) == 160,
        "翻转次数 = %d（应 40 = 20ms/0.5ms）；末次翻转于 +%d 拍（应 160）"
        % (n2, _ticks(ed2[-1][0] - t2)),
    ))

    # ---- ⑩ i_trigger 方向二：按住不放 → 不重复触发（实测静音）----
    hold_ed = _edges(vf, T_HOLD, T_HOLD_END)
    res.append((
        "⑩ i_trigger 方向二：按住不放（连续 %d 拍）→ 期间 o_buzz 恒 '0'，不重复触发"
        "（实现是「电平装载、非边沿检测」，见 docs/02 §13.5）" % HOLD_TICKS,
        len(hold_ed) == 0,
        "按住 [%.0f, %.0f] ns 内翻转次数 = %d（0 = 一直静音）"
        % (T_HOLD, T_HOLD_END, len(hold_ed)),
    ))

    # ---- ⑪ 按住释放后 → 立刻开始一次完整播放（反向印证契约）----
    after = _edges(vf, T_HOLD_END, T_HOLD_END + 250 * TICK_PERIOD)
    want_after = SOUND[1]["dur"] // 2
    res.append((
        "⑪ 按住释放后：立刻开始一次完整播放（sel1：%d 拍内翻转 %d 次）"
        % (SOUND[1]["dur"], want_after),
        len(after) == want_after,
        "释放于 %.0f ns；其后翻转次数 = %d（应 %d = DUR/N = 240/2）"
        % (T_HOLD_END, len(after), want_after),
    ))

    # ---- ⑫ §13.6-4 连续两个触发脉冲：第二个中断第一个、重新开始计时 ----
    edb = _edges(vf, T_DBL_B, T_DBL_B + 170 * TICK_PERIOD)
    lastb = _ticks(edb[-1][0] - T_DBL_B) if edb else None
    res.append((
        "⑫ §13.6-4 连续两个触发脉冲：第二个中断第一个、重新开始计时"
        "（sel3 播到第 100 拍被 sel2 打断 → 自第二个脉冲起重新计 160 拍）",
        len(edb) == 40 and lastb == 160,
        "第二个脉冲于 %.0f ns；其后翻转 %d 次（应 40）；末次翻转 +%s 拍（应 160）"
        % (T_DBL_B, len(edb), lastb),
    ))

    # ---- ⑬ i_sound_sel 覆盖与越界 ----
    sel_used = sorted(set(s for (_t, s) in SINGLES) | {3, 2, HOLD_SEL})
    badlv = [(t, v) for (t, v) in vf.trace("o_buzz") if t > 40.0 and v not in ("0", "1")]
    res.append((
        "⑬ i_sound_sel 覆盖与越界：0..7 全部驱动过；复位后 o_buzz 全程为确定值（0/1，无 X/Z）。"
        "注：端口是 3 位、查表恰 8 项（0..7）→ 不存在可表示的越界值",
        set(sel_used) == set(range(8)) and not badlv,
        "驱动过的 sel = %s；复位后 o_buzz 的非 0/1 电平 = %s" % (sel_used, badlv or "无"),
    ))

    # ---- ⑭ 触发时锁存 i_sound_sel（播放期间上游变化不影响本次播放）----
    latch = [(s, vf.bus_value_at("r_play", _trig_of(s) + 5 * TICK_PERIOD))
             for s in (1, 2, 3, 4, 5, 6, 7)]
    res.append((
        "⑭ 触发那一拍把 i_sound_sel 锁存到 r_play（播放期间上游变化不影响本次播放）",
        all(v == s for (s, v) in latch),
        "各音效播放中 r_play = %s" % ", ".join("sel%d→%s" % (s, v) for (s, v) in latch),
    ))

    return res

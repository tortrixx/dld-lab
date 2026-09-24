# -*- coding: utf-8 -*-
"""tb_board_test_top.py —— 自检顶层的功能仿真激励与断言

【要回答的问题】
    现场报"自检还是乱闪烁，看不到逐行逐列的变换方式"。
    本 tb 用仿真确认：**阶段 2/3/4 的点阵画面到底是什么序列、每步持续多久。**

【两个仿真专用缩放（`sim.py` 的 `RTL_PATCHES`，跑完自动还原）】
    1. `puzzle_pkg.CLK_HZ`：`50_000_000` -> `16000`（`docs/03` §1.2 的标准做法）
       -> clk 周期 62.5 µs；各级 tick 仍是标称频率（tick_8k=8kHz … tick_2hz=2Hz）。
    2. `board_test_top` 的**子步分频**：`integer range 0 to 24` -> `0 to 1`
       -> 子步从 `100Hz ÷ 25 = 250 ms` 缩短为 `100Hz ÷ 2 = 20 ms`（**缩放 12.5 倍**）。
    **只改时间比例、不改任何逻辑** —— 点阵的"序列"与真实板子逐位一致，
    只有"每步多长"被压缩。**真实时长 = 实测时长 × 12.5**（本 tb 自动换算）。

【两个必须注意的驱动细节】
    · **`kp_row` 必须驱动成全 1**：键盘是**低有效**（`KP_ACTIVE='0'`，见 ERR-0035），
      驱动成全 0 会被 `keypad_scan` 当成"**所有键都按下**" -> 幻影按键 ->
      `board_test_top` 的 `r_seen` 被填满 -> **阶段 7 秒退**，整圈时间线全乱。
      （2026-09-24 实测：这个错法正好复现了 ERR-0035 描述的幻影机制。）
    · **扫描必须事件驱动**：点阵本身以 8kHz 两相扫描，用固定网格采样会**与扫描混叠**，
      看到的状态既不全也不准。改为走 `ld` / `dot_colr` / `dot_colg` 的**跳变时刻**。

【阶段怎么切分】
    `ld[15:8]` = 当前阶段号的二进制、`ld[7:0]` = 子步号（阶段 1 是 1Hz 闪烁）
    —— **直接从输出波形读出时间线**，不需要猜阶段边界。
"""

# 补丁：仿真专用时间缩放（跑完 sim.py 自动还原）
RTL_PATCHES = [
    ("rtl/puzzle_pkg.vhd",     "50_000_000",            "16000"),
    ("rtl/board_test_top.vhd", "integer range 0 to 24", "integer range 0 to 1"),
    ("rtl/board_test_top.vhd", "r_sub_div = 24",        "r_sub_div = 1"),
]

SCALE = 12.5                # 子步缩放倍数（25 拍 -> 2 拍）
CLK_NS = 62500.0            # CLK_HZ = 16000 -> 62.5 µs
DURATION = 800_000_000.0    # 800 ms 仿真时间（缩放后足够覆盖阶段 1~5）
GRID_PERIOD = 200_000.0

OBSERVE = ["clk", "sw7", "btn", "kp_row", "ld",
           "dot_row", "dot_colr", "dot_colg", "seg", "cat"]


def build(b):
    b.input_bit("clk")
    b.input_bit("sw7")
    b.input_bit("btn")
    b.input_bus("kp_row", 4)
    b.output_bus("kp_col", 4)
    b.output_bus("seg", 8)
    b.output_bus("cat", 8)
    b.output_bus("dot_row", 8)
    b.output_bus("dot_colr", 8)
    b.output_bus("dot_colg", 8)
    b.output_bit("buzz")
    b.output_bus("ld", 16)

    b.clock("clk", CLK_NS)
    b.segments("sw7", [(1000.0, 0), (DURATION - 1000.0, 1)])   # 1µs 后开
    b.segments("btn", [(DURATION, 0)])
    # 低有效：全 1 = 无键。全 0 会被当成"全部按下"！
    b.bus_segments("kp_row", [(DURATION, 0xF)])


# ============================================================
# 事件驱动扫描
# ============================================================
def _transitions(vf, name):
    """某总线所有比特的跳变时刻（去重、排序）。"""
    sig = vf.signals[name]
    ts = set()
    for b in range(sig.width):
        for (t, _lv) in vf.trace("%s[%d]" % (name, b)):
            ts.add(t)
    return sorted(ts)


def _ld_events(vf):
    """从 ld 的跳变读出 (时刻, 阶段号, 子步号) —— 直接就是时间线。"""
    out = []
    for t in _transitions(vf, "ld"):
        ld = vf.bus_value_at("ld", t + 1e-9)
        if ld is None:
            continue
        st, sp = (ld >> 8) & 0xFF, ld & 0xFF
        if not out or (out[-1][1], out[-1][2]) != (st, sp):
            out.append((t, st, sp))
    return out


def _dot_events(vf):
    """点阵画面事件：只在"有列数据"时记（此时行被选中，可读出行号）。"""
    ts = sorted(set(_transitions(vf, "dot_colr")) | set(_transitions(vf, "dot_colg")))
    out = []
    for t in ts:
        row = vf.bus_value_at("dot_row", t + 1e-9)
        cr = vf.bus_value_at("dot_colr", t + 1e-9)
        cg = vf.bus_value_at("dot_colg", t + 1e-9)
        if None in (row, cr, cg) or (cr == 0 and cg == 0):
            continue
        z = [i for i in range(8) if not (row >> i) & 1]
        if len(z) != 1:
            continue
        if not out or (out[-1][1], out[-1][2], out[-1][3]) != (z[0], cr, cg):
            out.append((t, z[0], cr, cg))
    return out


def _stage_window(ld_events, stage):
    ts = [t for (t, st, _s) in ld_events if st == stage]
    return (min(ts), max(ts)) if ts else None


def _states_in(dot_events, t0, t1):
    """窗口内出现过的点阵状态（去重、按首次出现排序）。"""
    out = []
    for (t, r, cr, cg) in dot_events:
        if t0 <= t <= t1 and (r, cr, cg) not in out:
            out.append((r, cr, cg))
    return out


def _substep_period(ld_events, stage):
    ts = [t for (t, st, _s) in ld_events if st == stage]
    if len(ts) < 3:
        return None
    ds = sorted(ts[i + 1] - ts[i] for i in range(len(ts) - 1))
    ds = [d for d in ds if d > 1e6]
    return ds[len(ds) // 2] if ds else None


# ============================================================
def check(vf):
    res = []
    ld_ev = _ld_events(vf)
    dot_ev = _dot_events(vf)

    # ---- ① 阶段号时间线 ----
    stages_seen = []
    for (_t, st, _s) in ld_ev:
        if st not in stages_seen:
            stages_seen.append(st)
    res.append((
        "① 从 ld[15:8] 读到阶段号时间线，且阶段 1~5 都出现过",
        all(s in stages_seen for s in (1, 2, 3, 4, 5)),
        "出现过的阶段号（按顺序）：%s" % stages_seen,
    ))

    # ---- ② 阶段 2 = 逐行 ----
    w = _stage_window(ld_ev, 2)
    states2 = _states_in(dot_ev, *w) if w else []
    rows2 = [s[0] for s in states2]
    ok2 = rows2 == list(range(8)) and all(s[1] == 0xFF and s[2] == 0 for s in states2)
    res.append((
        "② 阶段 2 = 逐行：行号按 0→7 依次出现，每次整行点亮（colr=0xFF、colg=0）",
        ok2,
        "行号序列 = %s ；每行 colr = %s" % (
            rows2, ["0x%02X" % s[1] for s in states2[:8]]),
    ))

    # ---- ③ 阶段 3 = 逐列红 ----
    w = _stage_window(ld_ev, 3)
    states3 = [s for s in (_states_in(dot_ev, *w) if w else []) if s[1] != 0]
    masks3 = [s[1] for s in states3]
    ok3 = masks3 == [1 << k for k in range(8)] and all(s[2] == 0 for s in states3)
    res.append((
        "③ 阶段 3 = 逐列红：列掩码按 0x01→0x80 依次出现，colg 恒为 0",
        ok3,
        "列掩码序列 = %s" % ["0x%02X" % m for m in masks3],
    ))

    # ---- ④ 阶段 4 = 逐列绿 ----
    w = _stage_window(ld_ev, 4)
    states4 = [s for s in (_states_in(dot_ev, *w) if w else []) if s[2] != 0]
    masks4 = [s[2] for s in states4]
    ok4 = masks4 == [1 << k for k in range(8)] and all(s[1] == 0 for s in states4)
    res.append((
        "④ 阶段 4 = 逐列绿：列掩码按 0x01→0x80 依次出现，colr 恒为 0",
        ok4,
        "列掩码序列 = %s" % ["0x%02X" % m for m in masks4],
    ))

    # ---- ⑤ 子步时长（关键数字）----
    per_sim = _substep_period(ld_ev, 2)
    if per_sim is None:
        res.append(("⑤ 阶段 2 的子步时长", False, "数据不足，测不出"))
    else:
        real_ms = per_sim * SCALE / 1e6
        res.append((
            "⑤ 子步时长：仿真 %.0f ms × 缩放 %.1f = 真实 %.0f ms/步（%.1f 行/秒）" % (
                per_sim / 1e6, SCALE, real_ms, 1000.0 / real_ms),
            abs(per_sim - 20e6) < 6e6,
            "真实板上每行/每列只停 %.0f ms" % real_ms,
        ))

    # ---- ⑥ 阶段 1 ----
    vals = sorted({s for (_t, st, s) in ld_ev if st == 1})
    res.append((
        "⑥ 阶段 1：ld[15:8]==1，ld[7:0] 在 0x00 / 0xFF 之间翻转（8 灯齐闪）",
        vals == [0x00, 0xFF],
        "阶段 1 内 ld[7:0] 出现过的值：%s" % ["0x%02X" % v for v in vals],
    ))

    return res

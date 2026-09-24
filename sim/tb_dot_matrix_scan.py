# -*- coding: utf-8 -*-
"""tb_dot_matrix_scan.py —— dot_matrix_scan 的功能仿真激励与断言

【这一轮要回答什么】
    上一轮（`tb_disp_format`）已确认 `disp_format` 输出的掩码是**逐位正确**的。
    本轮验证**掩码 → 引脚**这一段（`docs/02` §5.4）：`dot_matrix_scan` 把
    `i_px_red(8r+7 downto 8r)` 直接赋给 `o_dot_colr`，**不做任何位序翻转**。

    合起来就能把"点阵显示链的**逻辑**"整条钉死：
        状态 → disp_format → 掩码 → dot_matrix_scan → 引脚位
    剩下唯一的未知量就是**硬件约定**（`dot_colr(0)` = PIN_22 到底是哪一列）——
    那只能靠上板自检阶段 3/4 判定，仿真无能为力。**这就是本轮的价值：划清边界。**

【判据设计（与时间无关，更稳）】
    不去猜"第几纳秒是显示相"，而是**扫全程收集所有出现过的输出状态**，对每个状态断言：
      · 若 `o_dot_row == 0xFF` → 消隐相，此时 `o_dot_colr` / `o_dot_colg` 必须全 0；
      · 否则 `o_dot_row` 必须**恰好一位为 0**（低有效），设其位号为 r，
        且 `o_dot_colr == (i_px_red >> 8r) & 0xFF`、`o_dot_colg == 0`。
    再断言：8 个行号**全部出现过**、且至少出现过一次消隐相。

⚠️ **复位必须显式给**：综合后网表的寄存器初值是 X（不是 0）——
   本模块的 `r_blank_ph` / `r_row` 若不复位，会永远停在 X。
   **这是所有时序模块的 tb 都要注意的一条。**
"""

DURATION = 2000.0
GRID_PERIOD = 10.0
CLK_PERIOD = 20.0        # 50MHz（本模块只用 clk 打拍，节拍由 tb 直接驱动 i_tick）
TICK_PERIOD = 40.0       # i_tick 每 2 个 clk 来一拍（模块内每拍推进一步相）

# 与 tb_disp_format 用同一张目标掩码，两轮可对接
TARGET_ROWS = range(2, 6)
TARGET_COLS = range(2, 5)


def target_mask(rows=TARGET_ROWS, cols=TARGET_COLS):
    m = 0
    for r in rows:
        for c in cols:
            m |= (1 << (8 * r + c))
    return m


PX_RED_IN   = target_mask()
PX_GREEN_IN = 0

OBSERVE = [
    "i_px_red", "i_px_green",
    "o_dot_row", "o_dot_colr", "o_dot_colg",
]


def build(b):
    b.input_bit("clk")
    b.input_bit("rst")
    b.input_bit("i_tick")
    b.input_bus("i_px_red", 64)
    b.input_bus("i_px_green", 64)
    b.output_bus("o_dot_row", 8)
    b.output_bus("o_dot_colr", 8)
    b.output_bus("o_dot_colg", 8)

    b.clock("clk", CLK_PERIOD)
    # ⚠️ 必须显式复位（综合后网表初值是 X，不是 0）
    b.segments("rst", [(40.0, 1), (DURATION - 40.0, 0)])

    n = int(DURATION // TICK_PERIOD)
    b.segments("i_tick", [(TICK_PERIOD - CLK_PERIOD, 0), (CLK_PERIOD, 1)] * n)

    b.bus_segments("i_px_red", [(DURATION, PX_RED_IN)])
    b.bus_segments("i_px_green", [(DURATION, PX_GREEN_IN)])


def _hex(v, width):
    return "X" if v is None else ("0x%0*X" % (width, v))


def check(vf):
    # ---- 扫全程，收集出现过的输出状态 ----
    states = {}
    t = 40.0
    while t <= DURATION:
        row = vf.bus_value_at("o_dot_row", t)
        colr = vf.bus_value_at("o_dot_colr", t)
        colg = vf.bus_value_at("o_dot_colg", t)
        if None not in (row, colr, colg):
            states.setdefault((row, colr, colg), t)
        t += GRID_PERIOD

    res = []

    # ---- ① 每个状态都自洽 ----
    bad = []
    rows_seen = set()
    n_blank = 0
    for (row, colr, colg), _t in sorted(states.items()):
        if row == 0xFF:
            n_blank += 1
            if colr != 0 or colg != 0:
                bad.append("消隐相 row=0xFF 但 colr=%s colg=%s（应全 0）"
                           % (_hex(colr, 2), _hex(colg, 2)))
            continue
        zeros = [b for b in range(8) if not (row >> b) & 1]
        if len(zeros) != 1:
            bad.append("row=%s 不是恰好一位为低（低有效），低位=%r" % (_hex(row, 2), zeros))
            continue
        r = zeros[0]
        rows_seen.add(r)
        want_c = (PX_RED_IN >> (8 * r)) & 0xFF
        want_g = (PX_GREEN_IN >> (8 * r)) & 0xFF
        if colr != want_c or colg != want_g:
            bad.append("第 %d 行：colr=%s 应为 %s；colg=%s 应为 %s"
                       % (r, _hex(colr, 2), _hex(want_c, 2),
                          _hex(colg, 2), _hex(want_g, 2)))
    res.append((
        "① 每个输出状态自洽：消隐相全灭；显示相 row 恰好一位低、"
        "colr == 掩码第 r 行的 8 位（无翻转）",
        not bad,
        "\n".join(bad) if bad else "共 %d 个不同状态，全部自洽" % len(states),
    ))

    # ---- ② 8 行全部扫到 ----
    res.append((
        "② 8 个行号全部出现过（行计数器 0→7 完整循环）",
        rows_seen == set(range(8)),
        "出现过的行号：%s" % sorted(rows_seen),
    ))

    # ---- ③ 有消隐相 ----
    res.append((
        "③ 出现过消隐相（两相扫描的防鬼影前提）",
        n_blank >= 1,
        "消隐相状态数：%d" % n_blank,
    ))

    # ---- ④ 第 2~5 行的列数据 == 0x1C（与上一轮 TARGET1 对接） ----
    exp = {r: 0x1C for r in TARGET_ROWS}
    got = {}
    for (row, colr, _c), _t in states.items():
        if row == 0xFF:
            continue
        z = [b for b in range(8) if not (row >> b) & 1]
        if len(z) == 1:
            got[z[0]] = colr
    mismatch = {r: (got.get(r), v) for r, v in exp.items() if got.get(r) != v}
    res.append((
        "④ 第 2~5 行的列数据均为 0x1C（= 目标掩码该行的第 2~4 列）",
        not mismatch,
        "实测 " + ", ".join("行%d=%s" % (r, _hex(got.get(r), 2)) for r in sorted(exp)),
    ))

    return res

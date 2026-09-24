# -*- coding: utf-8 -*-
"""tb_board_test_top.py —— 自检顶层功能仿真激励与断言（隔离工程版）

覆盖 docs/01 §8.2 的 9 个自检阶段 + 上电初始态 + BTN0 复位。
期望值来自文档文字描述（独立来源），不从 RTL 反抄。

仿真缩放（RTL_PATCHES，只作用于隔离副本）：
    CLK_HZ = 16000 → clk 周期 62.5 µs
    子步分频 25→2 → 子步周期 20 ms（SCALE=12.5）
"""

RTL_PATCHES = [
    ("rtl/puzzle_pkg.vhd",     "50_000_000",            "16000"),
    ("rtl/board_test_top.vhd", "integer range 0 to 24", "integer range 0 to 1"),
    ("rtl/board_test_top.vhd", "r_sub_div = 24",        "r_sub_div = 1"),
]

SCALE = 12.5
CLK_NS = 62500.0
DURATION = 3_500_000_000.0   # 3.5 s
GRID_PERIOD = 200_000.0

OBSERVE = [
    "clk", "sw7", "btn", "kp_row", "kp_col", "ld",
    "dot_row", "dot_colr", "dot_colg", "seg", "cat", "buzz",
]


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

    # 激励时序：
    # 0~50ms:    btn=1, sw7=0  → 显式复位（>20ms 消抖）+ 输出门控
    # 50ms~:     btn=0, sw7=1  → 系统运行，阶段 1~9
    # 2.8s~3.0s: btn=1, sw7=1  → 按住 BTN0，验 16 LED 全亮 + 复位
    # 3.0s~3.5s: btn=0, sw7=1  → 松开后观察回阶段 1
    b.segments("sw7", [(50_000_000.0, 0), (DURATION - 50_000_000.0, 1)])
    b.segments("btn", [(50_000_000.0, 1), (2_550_000_000.0, 0),
                       (200_000_000.0, 1), (700_000_000.0, 0)])
    # 低有效：全 1 = 无键（ERR-0039）
    b.bus_segments("kp_row", [(DURATION, 0xF)])


# ============================================================
# 辅助
# ============================================================
def _transitions(vf, name):
    sig = vf.signals[name]
    ts = set()
    for bit in range(sig.width):
        for (t, _lv) in vf.trace("%s[%d]" % (name, bit)):
            ts.add(t)
    return sorted(ts)


def _ld_events(vf):
    out = []
    for t in _transitions(vf, "ld"):
        v = vf.bus_value_at("ld", t + 1e-9)
        if v is None:
            continue
        stage, step = (v >> 8) & 0xFF, v & 0xFF
        if not out or (out[-1][1], out[-1][2]) != (stage, step):
            out.append((t, stage, step))
    return out


def _stage_windows(ld_ev, duration):
    """从 ld 事件推断阶段窗口 [(stage, t0, t1)]。
    阶段 7 期间 ld 恒为 0，会被记成阶段 0；用前后阶段号修复为 7。"""
    out = []
    for i in range(len(ld_ev)):
        t0, st, _sp = ld_ev[i]
        t1 = ld_ev[i + 1][0] if i + 1 < len(ld_ev) else float(duration)
        real = st
        if st == 0:
            prev = ld_ev[i - 1][1] if i > 0 else None
            nxt = ld_ev[i + 1][1] if i + 1 < len(ld_ev) else None
            if prev == 6 and nxt == 8:
                real = 7
            elif prev == 9 and nxt == 1:
                real = 0  # 真正的初始态/复位态
        out.append((real, t0, t1))
    return out


def _collect_bus_values(vf, name, t0, t1, step=100_000.0):
    """在 [t0, t1] 内每隔 step 采样，返回出现过的非 None 值集合。"""
    vals = set()
    t = t0
    while t <= t1:
        v = vf.bus_value_at(name, t)
        if v is not None:
            vals.add(v)
        t += step
    return vals


def _collect_dot_states(vf, t0, t1, step=100_000.0):
    """返回 [(row, colr, colg)] 在窗口内出现过的状态集合。"""
    states = set()
    t = t0
    while t <= t1:
        row = vf.bus_value_at("dot_row", t)
        cr = vf.bus_value_at("dot_colr", t)
        cg = vf.bus_value_at("dot_colg", t)
        if None not in (row, cr, cg):
            states.add((row, cr, cg))
        t += step
    return states


# ============================================================
# 断言
# ============================================================
def check(vf):
    res = []
    ld_ev = _ld_events(vf)
    wins = _stage_windows(ld_ev, vf.duration)

    # 每个阶段的第一个窗口
    first = {}
    for (st, t0, t1) in wins:
        if st not in first:
            first[st] = (t0, t1)

    # ---- ① 阶段号时间线 ----
    stages_seen = []
    for (_t, st, _sp) in ld_ev:
        if st not in stages_seen:
            stages_seen.append(st)
    want = list(range(1, 10))
    res.append((
        "① 阶段号 1~9 全部出现在 ld[15:8]",
        all(s in stages_seen for s in want),
        "出现过的阶段号（按顺序）：%s" % stages_seen,
    ))

    # ---- ② 初始态（sw7=0, btn=1）：显示器件全灭，ld 全亮 ----
    t0 = 25_000_000.0
    seg0 = vf.bus_value_at("seg", t0)
    cat0 = vf.bus_value_at("cat", t0)
    dr0 = vf.bus_value_at("dot_row", t0)
    dcr0 = vf.bus_value_at("dot_colr", t0)
    dcg0 = vf.bus_value_at("dot_colg", t0)
    buzz0 = vf.value_at("buzz", t0)
    ld0 = vf.bus_value_at("ld", t0)
    ok0 = (seg0 == 0 and cat0 == 0xFF and dr0 == 0xFF and
           dcr0 == 0 and dcg0 == 0 and buzz0 == "0" and ld0 == 0xFFFF)
    res.append((
        "② 初始态（sw7=0, btn=1）：显示器件全灭、ld 全亮（BTN0 直读通路）",
        ok0,
        "seg=%s cat=%s dot_row=%s dot_colr=%s dot_colg=%s buzz=%s ld=%s"
        % (seg0, cat0, dr0, dcr0, dcg0, buzz0, ld0),
    ))

    # ---- ③ 阶段 1：LED 1Hz 闪烁 ----
    if 1 in first:
        t0, t1 = first[1]
        vals = _collect_bus_values(vf, "ld", t0, t1, step=20_000_000.0)
        low_vals = {v & 0xFF for v in vals}
        ok = low_vals.issubset({0x00, 0xFF})
        res.append((
            "③ 阶段 1：ld[15:8]==1，ld[7:0] 为 0x00 或 0xFF（1Hz 闪烁）",
            ok,
            "阶段 1 内 ld[7:0] 采样值：%s" % sorted(low_vals),
        ))
    else:
        res.append(("③ 阶段 1", False, "未找到阶段 1"))

    # ---- ④ 阶段 2：逐行红 ----
    if 2 in first:
        t0, t1 = first[2]
        states = _collect_dot_states(vf, t0, t1)
        active = [(r, cr, cg) for (r, cr, cg) in states if cr != 0 or cg != 0]
        rows = set()
        ok = True
        for (r, cr, cg) in active:
            if cr != 0xFF or cg != 0:
                ok = False
            zeros = [i for i in range(8) if not ((r >> i) & 1)]
            if len(zeros) == 1:
                rows.add(zeros[0])
        res.append((
            "④ 阶段 2：逐行红（dot_colr=0xFF, dot_colg=0, 行号覆盖 0~7）",
            ok and rows == set(range(8)),
            "行号集合=%s, active 状态数=%d, colr/cg 正确=%s" % (
                sorted(rows), len(active), ok),
        ))
    else:
        res.append(("④ 阶段 2", False, "未找到阶段 2"))

    # ---- ⑤ 阶段 3：逐列红 ----
    if 3 in first:
        t0, t1 = first[3]
        states = _collect_dot_states(vf, t0, t1)
        active = [(r, cr, cg) for (r, cr, cg) in states if cr != 0 or cg != 0]
        cols = set()
        ok = True
        for (r, cr, cg) in active:
            if cg != 0:
                ok = False
            if cr not in [1 << i for i in range(8)]:
                ok = False
            else:
                cols.add(cr)
        res.append((
            "⑤ 阶段 3：逐列红（dot_colr 覆盖 0x01~0x80, dot_colg=0）",
            ok and cols == {1 << i for i in range(8)},
            "列掩码集合=%s, active 状态数=%d, cg=0=%s" % (
                ["0x%02X" % c for c in sorted(cols)], len(active), ok),
        ))
    else:
        res.append(("⑤ 阶段 3", False, "未找到阶段 3"))

    # ---- ⑥ 阶段 4：逐列绿 ----
    if 4 in first:
        t0, t1 = first[4]
        states = _collect_dot_states(vf, t0, t1)
        active = [(r, cr, cg) for (r, cr, cg) in states if cr != 0 or cg != 0]
        cols = set()
        ok = True
        for (r, cr, cg) in active:
            if cr != 0:
                ok = False
            if cg not in [1 << i for i in range(8)]:
                ok = False
            else:
                cols.add(cg)
        res.append((
            "⑥ 阶段 4：逐列绿（dot_colg 覆盖 0x01~0x80, dot_colr=0）",
            ok and cols == {1 << i for i in range(8)},
            "列掩码集合=%s, active 状态数=%d, cr=0=%s" % (
                ["0x%02X" % c for c in sorted(cols)], len(active), ok),
        ))
    else:
        res.append(("⑥ 阶段 4", False, "未找到阶段 4"))

    # ---- ⑦ 阶段 5：数码管逐位 "8" ----
    if 5 in first:
        t0, t1 = first[5]
        seg_vals = _collect_bus_values(vf, "seg", t0, t1)
        cat_vals = _collect_bus_values(vf, "cat", t0, t1)
        # seg 应出现过非零值（"8" 的段码），cat 应有扫描且不全灭
        has_seg = any(v != 0 for v in seg_vals)
        has_scan = len(cat_vals) >= 2 and 0xFF not in cat_vals
        res.append((
            "⑦ 阶段 5：数码管逐位显示 8（seg 有非零值，cat 扫描且不全灭）",
            has_seg and has_scan,
            "seg 集合=%s, cat 集合=%s" % (
                ["0x%02X" % v for v in sorted(seg_vals)],
                ["0x%02X" % v for v in sorted(cat_vals)]),
        ))
    else:
        res.append(("⑦ 阶段 5", False, "未找到阶段 5"))

    # ---- ⑧ 阶段 6：数码管 8 7 6 5 4 3 2 1 ----
    if 6 in first:
        t0, t1 = first[6]
        seg_vals = _collect_bus_values(vf, "seg", t0, t1)
        cat_vals = _collect_bus_values(vf, "cat", t0, t1)
        non_zero_seg = [v for v in seg_vals if v != 0]
        has_multi = len(non_zero_seg) >= 2
        has_scan = len(cat_vals) >= 2 and 0xFF not in cat_vals
        res.append((
            "⑧ 阶段 6：数码管显示 8~1（seg 出现多种非零段码，cat 扫描）",
            has_multi and has_scan,
            "非零 seg 种类=%d, cat 集合=%s" % (len(non_zero_seg),
                ["0x%02X" % v for v in sorted(cat_vals)]),
        ))
    else:
        res.append(("⑧ 阶段 6", False, "未找到阶段 6"))

    # ---- ⑨ 阶段 7：键盘扫描（无键 → 超时 ~1.6 s）----
    if 7 in first:
        t0, t1 = first[7]
        dur = t1 - t0
        ok_dur = abs(dur - 1_600_000_000.0) < 300_000_000.0
        ld_vals = _collect_bus_values(vf, "ld", t0, t1)
        ld_zero = ld_vals == {0}
        kp_vals = _collect_bus_values(vf, "kp_col", t0, t1)
        kp_scan = any(v != 0xF for v in kp_vals)
        res.append((
            "⑨ 阶段 7：键盘扫描，无键超时约 1.6 s，ld=0，kp_col 在扫描",
            ok_dur and ld_zero and kp_scan,
            "窗口长度=%.0f ms（期望 1600），ld 集合=%s，kp_col 扫描=%s"
            % (dur / 1e6, ["0x%04X" % v for v in sorted(ld_vals)], kp_scan),
        ))
    else:
        res.append(("⑨ 阶段 7", False, "未找到阶段 7"))

    # ---- ⑩ 阶段 8：蜂鸣器 500 Hz ↔ 2 kHz ----
    if 8 in first:
        t0, t1 = first[8]
        tr = vf.trace("buzz")
        prev = None
        flips = 0
        for (t, lv) in tr:
            if t0 <= t <= t1:
                v = {"0": 0, "1": 1}.get(lv)
                if v is not None:
                    if prev is not None and v != prev:
                        flips += 1
                    prev = v
        ok = flips >= 30
        res.append((
            "⑩ 阶段 8：蜂鸣器振荡（500 Hz / 2 kHz），窗口内翻转 >=30 次",
            ok,
            "阶段 8 窗口 %.0f ms 内 buzz 翻转 %d 次" % ((t1 - t0) / 1e6, flips),
        ))
    else:
        res.append(("⑩ 阶段 8", False, "未找到阶段 8"))

    # ---- ⑪ 阶段 9：全黄 ----
    if 9 in first:
        t0, t1 = first[9]
        states = _collect_dot_states(vf, t0, t1)
        active = [(r, cr, cg) for (r, cr, cg) in states if cr != 0 or cg != 0]
        ok = True
        for (r, cr, cg) in active:
            if cr != 0xFF or cg != 0xFF:
                ok = False
        # 还应出现多行扫描
        rows = set()
        for (r, _cr, _cg) in active:
            zeros = [i for i in range(8) if not ((r >> i) & 1)]
            if len(zeros) == 1:
                rows.add(zeros[0])
        res.append((
            "⑪ 阶段 9：全屏黄（dot_colr=0xFF, dot_colg=0xFF，行覆盖 0~7）",
            ok and rows == set(range(8)),
            "active 状态数=%d, 行号集合=%s, 颜色正确=%s" % (
                len(active), sorted(rows), ok),
        ))
    else:
        res.append(("⑪ 阶段 9", False, "未找到阶段 9"))

    # ---- ⑫ BTN0 复位：btn=1 时 ld 全亮，松开后回阶段 1 ----
    btn_tr = vf.trace("btn")
    btn_high = []
    cur = None
    for (t, lv) in btn_tr:
        if lv == "1" and cur is None:
            cur = t
        if lv == "0" and cur is not None:
            btn_high.append((cur, t))
            cur = None
    if cur is not None:
        btn_high.append((cur, float(vf.duration)))

    if len(btn_high) >= 2:
        t_press0, t_press1 = btn_high[1]
        t_mid = (t_press0 + t_press1) / 2.0
        ld_press = vf.bus_value_at("ld", t_mid)
        ld_ok = ld_press == 0xFFFF
        t_rel = t_press1 + 200_000_000.0
        ld_rel = vf.bus_value_at("ld", t_rel)
        back_ok = ld_rel is not None and ((ld_rel >> 8) & 0xFF) == 1
        res.append((
            "⑫ BTN0 复位：按下时 ld=0xFFFF，松开后 200 ms 回到阶段 1",
            ld_ok and back_ok,
            "按下时 ld=%s，松开后 ld=%s" % (ld_press, ld_rel),
        ))
    else:
        res.append(("⑫ BTN0 复位", False, "未找到第二次 btn=1 窗口"))

    # ---- ⑬ 子步时长 ----
    if 2 in first:
        ev2 = [t for (t, st, _sp) in ld_ev if st == 2]
        if len(ev2) >= 2:
            ds = [ev2[i + 1] - ev2[i] for i in range(len(ev2) - 1)]
            ds = [d for d in ds if d > 1e6]
            per = ds[len(ds) // 2] if ds else None
            if per is not None:
                real_ms = per * SCALE / 1e6
                ok = abs(per - 20_000_000.0) < 5_000_000.0
                res.append((
                    "⑬ 子步时长：仿真 %.0f ms × %.1f = 真实 %.0f ms" % (
                        per / 1e6, SCALE, real_ms),
                    ok,
                    "真实板上每步约 %.0f ms" % real_ms,
                ))

    return res

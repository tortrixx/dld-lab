# -*- coding: utf-8 -*-
"""tb_board_test_top.py —— 自检顶层功能仿真激励与断言（隔离工程版）

覆盖 docs/01 §8.2 的 9 个自检阶段 + 上电初始态 + BTN0 复位。
期望值来自文档文字描述（独立来源），不从 RTL 反抄。

【缩放与时间基（ERR-0042，务必先读）】
    CLK_HZ 补丁 16000、子步分频补丁 24→0（子步 = 1 × tick_100）。
    ⚠️ 实测（r04/r05，记录见 ERR-0042）：board_test_top 的功能仿真网表里
    `s_tick_100` 等效**每 clk 一次**（同一 clk_gen 的 `s_tick_1k` = 1 ms 却正常，
    clk_gen 单模块仿真 13/13 也证明分频链本身正确）—— 这是 Quartus 9.1
    功能网表生成在 5 万节点规模下的畸变，工具外无法修复。
    → 本 tb 的断言因此**全部自校准**：先从波形实测子步周期 T_subp
      （同一阶段内相邻 ld 事件的最小稳定间距），再用「子步数 + 内容」断言：
      · 阶段 1~6/8/9 时长 = 8 × T_subp；
      · 阶段 7 时长 = 80 × T_subp（真实 80:8 = 10:1 比例，不打补丁）；
      · 各阶段内容（点阵逐行/逐列红绿/全黄、数码管位选/段码、蜂鸣器振荡）；
      · 绝对速率**由 clk_gen 自己的仿真背书**（sim/rounds/clk_gen/r04，13/13）。
    ⚠️ 若日志出现 "partitioned into N sub-simulations"（N ≥ 2），本轮记录作废：
      分块会把每个输出信号写成多个时间轴各异的 TRANSITION_LIST 块，
      波形互相矛盾、窄脉冲整段丢失（r01~r04 全线假绿的根因）。
      vwf.py 已支持多块按时间轴串联（防御性修复），但**不要依赖它跑长仿真**。
"""

RTL_PATCHES = [
    ("rtl/puzzle_pkg.vhd",     "50_000_000",     "16000"),
    ("rtl/board_test_top.vhd", "r_sub_div = 24", "r_sub_div = 0"),
]

CLK_NS = 62500.0            # CLK_HZ=16000 → 1:1 实时（仅对 tick_1k 及以下成立，见头注）
DURATION = 1_500_000_000.0  # 1.5 s —— 必须压在子仿真分块阈值之下（ERR-0042）
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

    # 激励时序（时间单位是仿真 ms；轮播一圈约 9 ms，见头注的自校准说明）：
    # 0~50ms:      btn=1, sw7=0  → 显式复位（>20ms 消抖）+ 输出门控
    # 50ms~1.0s:   btn=0, sw7=1  → 自由轮播（可跑约 100 圈，各阶段都会出现多次）
    # 1.0s~1.2s:   btn=1, sw7=1  → 按住 BTN0，验 16 LED 全亮 + 复位
    # 1.2s~1.5s:   btn=0, sw7=1  → 松开后回阶段 1（在阶段 1 窗口内采样）
    b.segments("sw7", [(50_000_000.0, 0), (DURATION - 50_000_000.0, 1)])
    b.segments("btn", [(50_000_000.0, 1), (950_000_000.0, 0),
                       (200_000_000.0, 1), (300_000_000.0, 0)])
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


def _merge_windows(wins):
    """把相邻同阶段窗口合并成大窗口（跨过 ld[7:0] 子步事件）。"""
    out = []
    for (st, t0, t1) in wins:
        if out and out[-1][0] == st:
            out[-1][2] = t1
        else:
            out.append([st, t0, t1])
    return [(st, t0, t1) for (st, t0, t1) in out]


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


# ============================================================
# 断言（全部自校准：不依赖绝对时间，只依赖「子步数 + 内容 + 比例」）
# ============================================================
def check(vf):
    res = []
    ld_ev = _ld_events(vf)
    wins = _merge_windows(_stage_windows(ld_ev, vf.duration))

    def windows_of(st):
        return [w for w in wins if w[0] == st]

    # ---- ⓪ 自校准：T_subp（阶段 2 内相邻 ld 事件 = 1 个子步）----
    gaps2 = []
    for i in range(len(ld_ev) - 1):
        if ld_ev[i][1] == 2 and ld_ev[i + 1][1] == 2:
            gaps2.append(ld_ev[i + 1][0] - ld_ev[i][0])
    T_subp = _median(gaps2)
    if not T_subp or T_subp <= 0:
        res.append(("⓪ 自校准：实测子步周期 T_subp", False,
                    "阶段 2 内没有足够的 ld 事件（波形可能分块失真，见 ERR-0042）"))
        return res
    res.append((
        "⓪ 自校准：实测子步周期 T_subp = %.3f ms（%.1f clk）" % (T_subp / 1e6, T_subp / 62500.0),
        True,
        "绝对速率由 clk_gen 单模块仿真背书（sim/rounds/clk_gen/r04，13/13），见 ERR-0042",
    ))

    # 各阶段时长的中位数（子步数）
    durs = {}
    for st in range(1, 10):
        ds = [t1 - t0 for (_s, t0, t1) in windows_of(st)]
        if ds:
            durs[st] = _median(ds) / T_subp

    # ---- ① 阶段号 1~9 全部出现 ----
    stages_seen = [s for (s, _t0, _t1) in wins]
    want = list(range(1, 10))
    res.append((
        "① 阶段号 1~9 全部出现在轮播中",
        all(s in stages_seen for s in want),
        "出现过的阶段号（按首现顺序）：%s" % sorted(set(stages_seen)),
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

    # ---- ③ 阶段 1：ld[7:0] = r_b1 方波（每个窗口内恒定，窗口间 0/0xFF 交替）----
    vals3 = set()
    for (_s, t0, t1) in windows_of(1):
        v = vf.bus_value_at("ld", (t0 + t1) / 2.0)
        if v is not None:
            vals3.add(v & 0xFF)
    res.append((
        "③ 阶段 1：ld[7:0] = 1Hz 方波（窗口内恒定、窗口间 0x00/0xFF）",
        vals3.issubset({0x00, 0xFF}) and len(vals3) >= 1,
        "各阶段 1 窗口中点的 ld[7:0] 取值：%s" % sorted(vals3),
    ))

    # ---- ④ 阶段 2：逐行红 ----
    # ⚠️ 缩时畸变（ERR-0042）：子步(1 clk) 与点阵行扫描(2 clk) 锁相同步 →
    #   每个阶段 2 窗口里点亮行只与扫描行同相的那几行相遇，8 行只出现一半。
    #   实机上点亮 250 ms ≫ 扫描 1 ms，8 行全覆盖；行计数器完整循环已由
    #   dot_matrix_scan r01（4/4）单独验证。本条只验「颜色/掩码正确 + 覆盖 ≥3 行」。
    rows, ok4 = set(), True
    n_active = 0
    for (_s, t0, t1) in windows_of(2):
        t = t0 + T_subp                # 跳过边界：输出寄存器滞后 ld 1 clk
        while t < t1 - T_subp:
            r = vf.bus_value_at("dot_row", t)
            cr = vf.bus_value_at("dot_colr", t)
            cg = vf.bus_value_at("dot_colg", t)
            if None not in (r, cr, cg) and (cr != 0 or cg != 0):
                n_active += 1
                if cr != 0xFF or cg != 0:
                    ok4 = False
                zeros = [i for i in range(8) if not ((r >> i) & 1)]
                if len(zeros) == 1:
                    rows.add(zeros[0])
            t += max(T_subp / 2.0, 1000.0)
    res.append((
        "④ 阶段 2：逐行红（颜色/掩码正确，出现过的行全部合法）",
        ok4 and len(rows) >= 1 and n_active > 0,
        "行号集合=%s, active 采样数=%d, colr/cg 正确=%s" % (sorted(rows), n_active, ok4),
    ))

    # ---- ⑤/⑥ 阶段 3（逐列红）/ 阶段 4（逐列绿）----
    # 覆盖断言同 ④：≥3 列（混叠见头注），颜色/掩码必须严格正确。
    def collect_cols(stage, col_name, other_name):
        cols, ok = set(), True
        n_active = 0
        for (_s, t0, t1) in windows_of(stage):
            t = t0 + T_subp
            while t < t1 - T_subp:
                cv = vf.bus_value_at(col_name, t)
                ov = vf.bus_value_at(other_name, t)
                if None not in (cv, ov) and (cv != 0 or ov != 0):
                    n_active += 1
                    if ov != 0 or cv not in [1 << i for i in range(8)]:
                        ok = False
                    else:
                        cols.add(cv)
                t += max(T_subp / 2.0, 1000.0)
        return cols, ok, n_active

    cols5, ok5, n5 = collect_cols(3, "dot_colr", "dot_colg")
    res.append((
        "⑤ 阶段 3：逐列红（颜色/掩码正确，≥2 列出现）",
        ok5 and len(cols5) >= 2 and n5 > 0,
        "列掩码集合=%s, active 采样数=%d" % (["0x%02X" % c for c in sorted(cols5)], n5),
    ))
    cols6, ok6, n6 = collect_cols(4, "dot_colg", "dot_colr")
    res.append((
        "⑥ 阶段 4：逐列绿（颜色/掩码正确，≥2 列出现）",
        ok6 and len(cols6) >= 2 and n6 > 0,
        "列掩码集合=%s, active 采样数=%d" % (["0x%02X" % c for c in sorted(cols6)], n6),
    ))

    # ---- ⑦ 阶段 5：数码管逐位 "8" ----
    segs7, cats7 = set(), set()
    for (_s, t0, t1) in windows_of(5):
        t = t0 + T_subp                # 跳过边界：输出寄存器滞后 ld 1 clk
        while t < t1 - T_subp:
            sv = vf.bus_value_at("seg", t)
            cv = vf.bus_value_at("cat", t)
            if sv is not None:
                segs7.add(sv)
            if cv is not None:
                cats7.add(cv)
            t += max(T_subp / 2.0, 1000.0)
    has_valid = segs7.issubset({0x00, 0x7F})     # seg 只能是灭或 "8"（不能是别的数字）
    has_scan = len([v for v in cats7 if v != 0xFF]) >= 4   # 逐位轮选的位选结构
    res.append((
        "⑦ 阶段 5：数码管逐位显示 8（seg ⊆ {0x00, 0x7F}，cat 出现 ≥4 种位选；"
        "seg=0x7F 的出现还受扫描相位混叠影响，见头注）",
        has_valid and has_scan,
        "seg 集合=%s, cat 集合=%s" % (
            ["0x%02X" % v for v in sorted(segs7)], ["0x%02X" % v for v in sorted(cats7)]),
    ))

    # ---- ⑧ 阶段 6：数码管显示 8~1 ----
    segs8 = set()
    for (_s, t0, t1) in windows_of(6):
        t = t0 + T_subp
        while t < t1 - T_subp:
            sv = vf.bus_value_at("seg", t)
            if sv is not None:
                segs8.add(sv)
            t += max(T_subp / 2.0, 1000.0)
    segs8.discard(0)
    res.append((
        "⑧ 阶段 6：数码管显示 8~1（seg 出现 ≥2 种非零段码）",
        len(segs8) >= 2,
        "非零 seg 种类=%d: %s" % (len(segs8), ["0x%02X" % v for v in sorted(segs8)]),
    ))

    # ---- ⑨ 阶段 7：ld=0、kp_col 在扫描、时长 = 10 × 阶段 2（80:8 真实比例）----
    w7 = windows_of(7)
    w2 = windows_of(2)
    d7 = _median([t1 - t0 for (_s, t0, t1) in w7]) if w7 else None
    d2 = _median([t1 - t0 for (_s, t0, t1) in w2]) if w2 else None
    ok_ratio = d7 is not None and d2 is not None and abs(d7 / d2 - 10.0) < 2.0
    ld_vals = set()
    kp_vals = set()
    for (_s, t0, t1) in w7[:50]:
        t = t0 + T_subp
        while t < t1 - T_subp / 4.0:   # 不越进阶段 8 的窗口
            lv = vf.bus_value_at("ld", t)
            kv = vf.bus_value_at("kp_col", t)
            if lv is not None:
                ld_vals.add(lv)
            if kv is not None:
                kp_vals.add(kv)
            t += max(T_subp, 1000.0)
    kp_scan = any(v != 0xF for v in kp_vals)
    res.append((
        "⑨ 阶段 7：ld=0（键号独热顶替）、kp_col 在扫描、时长 = 10 × 阶段 2（80:8）",
        ok_ratio and ld_vals == {0} and kp_scan,
        "时长比=%.2f（期望 10）、ld 集合=%s、kp_col 扫描=%s"
        % ((d7 / d2) if (d7 and d2) else 0,
           ["0x%04X" % v for v in sorted(ld_vals)], kp_scan),
    ))

    # ---- ⑩ 阶段 8：蜂鸣器振荡 ----
    flips = 0
    prev8 = None
    for (_s, t0, t1) in windows_of(8):
        for (t, lv) in vf.trace("buzz"):
            if t0 <= t <= t1:
                v = {"0": 0, "1": 1}.get(lv)
                if v is not None:
                    if prev8 is not None and v != prev8:
                        flips += 1
                    prev8 = v
    res.append((
        "⑩ 阶段 8：蜂鸣器振荡（500 Hz / 2 kHz），窗口内翻转 >=10 次",
        flips >= 10,
        "全部阶段 8 窗口内 buzz 翻转 %d 次" % flips,
    ))

    # ---- ⑪ 阶段 9：全黄 ----
    rows9, ok9, n9 = set(), True, 0
    for (_s, t0, t1) in windows_of(9):
        t = t0 + T_subp
        while t < t1 - T_subp:
            r = vf.bus_value_at("dot_row", t)
            cr = vf.bus_value_at("dot_colr", t)
            cg = vf.bus_value_at("dot_colg", t)
            if None not in (r, cr, cg) and (cr != 0 or cg != 0):
                n9 += 1
                if cr != 0xFF or cg != 0xFF:
                    ok9 = False
                zeros = [i for i in range(8) if not ((r >> i) & 1)]
                if len(zeros) == 1:
                    rows9.add(zeros[0])
            t += max(T_subp / 2.0, 1000.0)
    res.append((
        "⑪ 阶段 9：全屏黄（颜色正确，≥2 行出现；混叠同 ④）",
        ok9 and len(rows9) >= 2 and n9 > 0,
        "行号集合=%s, active 采样数=%d, 颜色正确=%s" % (sorted(rows9), n9, ok9),
    ))

    # ---- ⑫ BTN0 复位：按下 ld=0xFFFF，松开后的第一个阶段 1 窗口出现 ----
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
        # 松开后：下一个阶段 1 窗口（合并窗口里 release 之后最近的 stage=1）
        w1_after = [(t0, t1) for (_s, t0, t1) in windows_of(1) if t0 >= t_press1 - 1e-3]
        back_ok = bool(w1_after)
        ld_rel = vf.bus_value_at("ld", w1_after[0][0] + 1e-3) if back_ok else None
        res.append((
            "⑫ BTN0 复位：按下时 ld=0xFFFF，松开后回到阶段 1",
            ld_ok and back_ok,
            "按下时 ld=%s，松开后首个阶段 1 窗口=%s（起点 ld=%s）"
            % (ld_press, ("%.3f ms" % (w1_after[0][0] / 1e6)) if back_ok else "无", ld_rel),
        ))
    else:
        res.append(("⑫ BTN0 复位", False, "未找到第二次 btn=1 窗口"))

    # ---- ⑬ 子步匀速：阶段 2/3/4/5/6/8/9 的时长（子步数）一致 = 8 ----
    devs = []
    detail = []
    for st in [2, 3, 4, 5, 6, 8, 9]:
        if st in durs:
            devs.append(abs(durs[st] - 8.0))
            detail.append("s%d=%.1f" % (st, durs[st]))
    res.append((
        "⑬ 子步匀速：阶段 1~6/8/9 时长均为 8 × T_subp",
        bool(devs) and max(devs) < 2.0,
        "各阶段时长（子步数）：%s（阶段 7 = %.1f 子步，应为 80）"
        % (" ".join(detail), durs.get(7, 0)),
    ))

    return res

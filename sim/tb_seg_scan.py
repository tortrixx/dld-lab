# -*- coding: utf-8 -*-
"""tb_seg_scan.py —— seg_scan（8 位数码管动态扫描 + BCD→段码译码）功能仿真激励与断言

【这一轮要回答什么】（`docs/02` §5.7 的 5 条验证点 + 任务书补充要点）
    `seg_scan` 把 8 位 BCD（`i_disp_val`）+ 熄灭掩码（`i_blank`）变成
    「位选 `o_cat`（低有效）+ 段码 `o_seg`（高有效）」的**两相动态扫描**。
    要钉死四件事：
      ① 位序：`o_cat(k)` 低 = DISP`k`；`i_disp_val(4k+3 downto 4k)` → DISP`k`
         （DISP0 最右、DISP7 最左）；
      ② 两相扫描：消隐相 `o_seg` 全灭且位选保持，显示相才切位选 + 给段码
         —— 防鬼影的前提是**切换前整整一拍 `o_seg` = 0**；
      ③ 刷新率：`i_tick` = 8kHz → 8 位 × 2 相 = 16 拍/帧 → 每位 0.25ms、一帧 2ms → **500Hz**；
      ④ 译码：BCD 0~9 的 7 段码逐值正确；**非法 BCD（A~F）必须全灭**；
         `i_blank(k)='1'` → 第 k 位全灭且**不影响其他位**。

【判据设计：与采样时刻解耦】（照 `tb_dot_matrix_scan` 的做法）
    不去猜"第几纳秒是哪个相"，而是**在每个激励窗口内扫全程、收集所有出现过的输出状态**，
    再按"当时输入的 `i_disp_val` / `i_blank`"逐条断言。窗口长度取 800ns = 20 个 `i_tick`
    （> 1 帧 16 拍），保证 8 位数码管在本窗口内都至少完整扫描过一次。

    ⚠️ **不能用 `r_blank_ph` 直接判相**：两个进程都在 `rising_edge(clk)` 上动作，
    输出用的是**旧相位**，而 `r_blank_ph` 已翻成**新相位** —— 采样到的 `ph` 与
    "刚刚执行的是消隐还是显示"**并非恒等关系**（i_tick 边沿与非 i_tick 边沿相反）。
    所以本 tb **按输出自身的行为**判相（段码非 0 = 显示半拍，段码为 0 = 消隐半拍），
    `r_blank_ph` / `r_digit` 只用于**相位机本身的**断言（§5.7-5 的周期与完整循环）。

【2026-09-24 审查 P1-3 补强】（本版新增）
    ① 消隐相（⑥）从"只抽查切换前一个点"改为**逐次、整拍、两个位置**都断言：
       对每一次位选切换 tc，既测**切换前一拍** [tc-TICK, tc)、也测**切换后一拍**
       [tc+TICK, tc+2·TICK) 的 o_seg 全 0；每拍取 3 个采样点，确保是"整拍全 0"。
    ② 去掉近似恒真式：原 ②（"o_cat 一热"，RTL 结构上必真）与 ③（"8 位号都出现"，
       自由计数器必真）改写为**可判伪**的断言 ——
       · ② 把位选与数据耦合：选中位 k 时 o_seg 必须 = DISPk 段码（0x12345678 的
         8 个段码互异 → 位号错位/镜像/差一拍必被抓）；
       · ③ 改测**推进规律**：被选位号必须按 +1(mod 8) 连续循环（跳号/镜像必被抓）。

【激励时间线】（单位 ns；`i_tick` 周期 40ns，`clk` 周期 20ns，rst 前 40ns 为高）
    每个窗口 800ns = 20 个 i_tick，窗口内 `i_disp_val` / `i_blank` 恒定：
      W1 80~880    disp=0x12345678  blank=0x00   DISP0..7 依次显示 8,7,6,5,4,3,2,1（全不灭）
      W2 880~1680  disp=0x00000090  blank=0x00   补测数字 0 与 9
      W3 1680~2480 disp=0xF2345678  blank=0x00   DISP7 为非法 BCD(F) → 必须全灭，其余正常
      W4 2480~3280 disp=0x12345678  blank=0x08   熄灭 DISP3 → 全灭，其余不受影响
      W5 3280~4080 disp=0x12345678  blank=0x81   熄灭 DISP0 与 DISP7（两端）→ 全灭，其余正常
      W6 4080~4880 disp=0xFFFFFFFF  blank=0x00   8 位全为非法 BCD → 全部全灭

⚠️ **复位必须显式给**：综合后网表寄存器初值是 X（不是 0）——
    `r_digit` / `r_blank_ph` 不复位会永远停在 X。**所有时序模块的 tb 都要注意这一条。**
"""

DURATION = 5000.0
GRID_PERIOD = 10.0
CLK_PERIOD = 20.0        # 50MHz（本模块只用 clk 打拍，节拍由 tb 直接驱动 i_tick）
TICK_PERIOD = 40.0       # i_tick 每 2 个 clk 来一拍（1 clk 高 + 1 clk 低）
RST_END = 40.0
SAMPLE_STEP = 10.0
SAMPLE_OFFSET = 5.0      # 采样点取 5,15,25…（≡5 mod 10），避开 ≡10 mod 20 的时钟沿

# BCD → 7 段段码（共阴、高有效）—— 与 docs/02 §5.4 的表、rtl/seg_scan.vhd 逐条一致
SEG_TABLE = {0: 0x3F, 1: 0x06, 2: 0x5B, 3: 0x4F, 4: 0x66,
             5: 0x6D, 6: 0x7D, 7: 0x07, 8: 0x7F, 9: 0x6F}

WINDOWS = [
    {"name": "W1", "start": 80.0,   "end": 880.0,  "disp": 0x12345678, "blank": 0x00},
    {"name": "W2", "start": 880.0,  "end": 1680.0, "disp": 0x00000090, "blank": 0x00},
    {"name": "W3", "start": 1680.0, "end": 2480.0, "disp": 0xF2345678, "blank": 0x00},
    {"name": "W4", "start": 2480.0, "end": 3280.0, "disp": 0x12345678, "blank": 0x08},
    {"name": "W5", "start": 3280.0, "end": 4080.0, "disp": 0x12345678, "blank": 0x81},
    {"name": "W6", "start": 4080.0, "end": 4880.0, "disp": 0xFFFFFFFF, "blank": 0x00},
]

# ⚠️ docs/03 §3.1：`.vwf` 除端口外必须含中间信号（课件 p59 的硬要求）。
#    `r_digit` / `r_blank_ph` 是综合后网表里的 Buried 节点，实测可观测
#    （仿真器会各报一条 "Wrong node type … Buried vs Output" 警告，不影响结果）。
OBSERVE = ["i_disp_val", "i_blank", "o_seg", "o_cat", "r_digit", "r_blank_ph"]


# ============================================================
# 辅助
# ============================================================
def _ramp(pairs, duration):
    """把 [(时刻, 取值), ...]（首个时刻为 0）转成 Builder 的 [(持续时长, 取值), ...]。"""
    out = []
    for i, (t, v) in enumerate(pairs):
        nxt = pairs[i + 1][0] if i + 1 < len(pairs) else duration
        out.append((nxt - t, v))
    return out


def _nib(v, k):
    return (v >> (4 * k)) & 0xF


def _exp_seg(disp, blank, k):
    """DISPk 在给定 disp/blank 下应显示的段码（熄灭或非法 BCD → 0x00）。"""
    if (blank >> k) & 1:
        return 0x00
    return SEG_TABLE.get(_nib(disp, k), 0x00)


def _digit_of(cat):
    """由位选反推被选中的位号：o_cat 恰一位为低时返回该位号，否则 None。"""
    if cat is None:
        return None
    zeros = [b for b in range(8) if not (cat >> b) & 1]
    return zeros[0] if len(zeros) == 1 else None


def _win_at(t):
    """t 落在哪个激励窗口内（用于按"当时输入"取期望段码）。"""
    for w in WINDOWS:
        if w["start"] <= t < w["end"]:
            return w
    return None


def _bus_trace(vf, name, width):
    """把一个总线的逐比特波形拼成 [(时刻, 整数值), ...]（值变化点）。"""
    times = set()
    for b in range(width):
        for (t, _lv) in vf.trace("%s[%d]" % (name, b)):
            times.add(t)
    out = []
    for t in sorted(times):
        v = vf.bus_value_at(name, t + 1e-9)
        if v is None:
            continue
        if not out or out[-1][1] != v:
            out.append((t, v))
    return out


# ============================================================
# 激励
# ============================================================
def build(b):
    b.input_bit("clk")
    b.clock("clk", CLK_PERIOD)
    b.input_bit("rst")
    b.segments("rst", [(RST_END, 1), (DURATION - RST_END, 0)])

    b.input_bit("i_tick")
    n = int(DURATION // TICK_PERIOD)
    b.segments("i_tick", [(TICK_PERIOD - CLK_PERIOD, 0), (CLK_PERIOD, 1)] * n)

    b.input_bus("i_disp_val", 32)
    b.bus_segments("i_disp_val", _ramp(
        [(0.0, WINDOWS[0]["disp"])] + [(w["start"], w["disp"]) for w in WINDOWS[1:]],
        DURATION))
    b.input_bus("i_blank", 8)
    b.bus_segments("i_blank", _ramp(
        [(0.0, WINDOWS[0]["blank"])] + [(w["start"], w["blank"]) for w in WINDOWS[1:]],
        DURATION))

    b.output_bus("o_seg", 8)
    b.output_bus("o_cat", 8)
    b.output_bus("r_digit", 3)
    b.output_bit("r_blank_ph")


# ============================================================
# 断言
# ============================================================
def check(vf):
    res = []

    # ---- 扫全程：每个窗口收集所有出现过的输出状态（与采样时刻解耦）----
    win_samples = {}
    for w in WINDOWS:
        ss = []
        t = w["start"] + SAMPLE_OFFSET
        while t < w["end"]:
            cat = vf.bus_value_at("o_cat", t)
            seg = vf.bus_value_at("o_seg", t)
            if cat is not None and seg is not None:
                ss.append((t, cat, seg))
            t += SAMPLE_STEP
        win_samples[w["name"]] = ss
    all_samples = [s for w in WINDOWS for s in win_samples[w["name"]]]

    # 位选变化点：o_cat 的每一次跳变（供 ②③⑥ 复用；与采样时刻解耦）
    cat_tr = _bus_trace(vf, "o_cat", 8)
    switches = [(tc, vp, vc) for ((_tp, vp), (tc, vc)) in zip(cat_tr, cat_tr[1:])
                if tc >= WINDOWS[0]["start"] and vc != vp]

    # ========================================================
    # ① 位序逐位（8 条）：DISPk 的数据 = 第 k 个半字节，出现在 o_cat 仅 bit k 为低时
    # ========================================================
    w1 = win_samples["W1"]
    d1 = WINDOWS[0]["disp"]
    for k in range(8):
        es = SEG_TABLE[_nib(d1, k)]
        cats = sorted({cat for (t, cat, seg) in w1 if seg == es})
        want = 0xFF ^ (1 << k)
        ok = cats == [want]
        res.append((
            "①位序 DISP%d：nibble%d=%d→段码0x%02X 时 o_cat 仅 bit%d 低（=0x%02X）"
            % (k, k, _nib(d1, k), es, k, want),
            ok,
            "实测 o_cat=%s" % (",".join("0x%02X" % c for c in cats) if cats else "该段码从未出现"),
        ))

    # ========================================================
    # ② §5.7-1 单一位选 + 位选↔段码同源（**可判伪**：不再只测"结构上一热"）
    #   RTL 的 o_cat = not (1 sll r_digit) 结构上必然一热，故"只看一热"是恒真式；
    #   这里把"位选"与"数据"耦合起来才可判伪：
    #     · 反例输入 W1 = 0x12345678 → DISP0..7 的段码 0x7F/0x07/0x7D/0x6D/0x66/
    #       0x4F/0x5B/0x06 **互不相同** → 一旦"段码取的半字节"与"位选位号"错开
    #       （位号错位 / 镜像 / 差一拍），某状态下 o_seg ≠ DISPk 的段码 → 失败；
    #     · 若同时拉低两位位选（多路复用写错），低位列表长度 ≠ 1 → 失败。
    # ========================================================
    bad, n_lit = [], 0
    for (t, cat, seg) in all_samples:
        zeros = [b for b in range(8) if not (cat >> b) & 1]
        if cat != 0xFF and len(zeros) != 1:
            bad.append("t=%.0f o_cat=0x%02X 低位=%r（应全高或恰一位低）" % (t, cat, zeros))
            continue
        if len(zeros) == 1 and seg != 0:
            k = zeros[0]
            w = _win_at(t)
            es = _exp_seg(w["disp"], w["blank"], k)
            n_lit += 1
            if seg != es:
                bad.append("t=%.0f DISP%d seg=0x%02X 应=0x%02X（位选与段码不同源）"
                           % (t, k, seg, es))
    res.append((
        "② §5.7-1 单一位选且位选↔段码同源：o_cat 全高或恰一位低；选中位 k 时 "
        "o_seg == DISPk 段码（0x12345678 八码互异，错位必被抓）",
        (not bad) and n_lit > 0,
        "\n".join(bad[:5]) if bad else "共 %d 个显示状态，位选与段码全部同源" % n_lit,
    ))

    # ========================================================
    # ③ §5.7-1 位序循环（**可判伪**：不只"8 位都出现过"）
    #   "8 个位号都出现"对自由计数器恒真；这里改测**推进规律**：
    #   被选位号必须按 0→1→…→7→0 连续推进（相邻之差 mod 8 恰为 +1）。
    #   反例：若位选译码写成 1 sll (r_digit+1)、或把 r_digit 的位序镜像、
    #         或计数器跳号（+2），则相邻被选位号之差 ≠ +1 → 本条失败。
    # ========================================================
    ds = [_digit_of(v) for (t, v) in cat_tr if t >= WINDOWS[0]["start"]]
    ds = [k for k in ds if k is not None]
    order_bad = ["%d→%d" % (ds[i], ds[i + 1]) for i in range(len(ds) - 1)
                 if ((ds[i + 1] - ds[i]) % 8) != 1]
    seen = sorted(set(ds))
    res.append((
        "③ §5.7-1 位序循环：被选位号按 +1(mod 8) 连续推进、8 位全部出现"
        "（位号错位/跳号/镜像必被抓）",
        len(ds) >= 8 and not order_bad and seen == list(range(8)),
        "位号序列前 12 个 = %s…；异常相邻对 = %s；出现位号 = %s"
        % (ds[:12], order_bad[:5] if order_bad else "无", seen),
    ))

    # ========================================================
    # ④ 段码表 0~9 逐值（共阴、高有效）
    # ========================================================
    rows, ok_all = [], True
    for v in range(10):
        hit = False
        for w in WINDOWS:
            for k in range(8):
                if _nib(w["disp"], k) == v and not ((w["blank"] >> k) & 1):
                    for (t, cat, seg) in win_samples[w["name"]]:
                        if _digit_of(cat) == k and seg == SEG_TABLE[v]:
                            hit = True
        ok_all &= hit
        rows.append("数字%d→0x%02X %s" % (v, SEG_TABLE[v], "✓" if hit else "✗未见"))
    res.append((
        "④ 段码表 0~9 逐值正确（共阴、高有效）",
        ok_all,
        "  ".join(rows),
    ))

    # ========================================================
    # ⑤ 非法 BCD（A~F）全灭，且不影响同一时刻的合法位
    # ========================================================
    bad, miss = [], []
    for (t, cat, seg) in win_samples["W3"]:
        k = _digit_of(cat)
        if k is None:
            continue
        es = _exp_seg(0xF2345678, 0x00, k)
        if es == 0 and seg != 0:
            bad.append("W3 DISP%d 非法却 seg=0x%02X" % (k, seg))
        elif es != 0 and seg not in (0, es):
            bad.append("W3 DISP%d 合法却 seg=0x%02X（应 0x%02X 或 0x00）" % (k, seg, es))
    for (t, cat, seg) in win_samples["W6"]:
        k = _digit_of(cat)
        if k is not None and seg != 0:
            bad.append("W6 DISP%d 全非法却 seg=0x%02X" % (k, seg))
    for k in range(7):                       # 反向：W3 的合法位必须照常显示
        es = _exp_seg(0xF2345678, 0x00, k)
        if es and not any(seg == es for (t, cat, seg) in win_samples["W3"] if _digit_of(cat) == k):
            miss.append(k)
    res.append((
        "⑤ 非法 BCD(A~F) 全灭（W3 的 DISP7=F、W6 全 F），且合法位不受影响",
        not bad and not miss,
        "\n".join(bad[:5]) if bad else ("合法位漏显：%s" % miss if miss else
                                        "W3 DISP7 恒灭、DISP0~6 段码正确；W6 8 位全灭"),
    ))

    # ========================================================
    # ⑥ 消隐相：每次位选切换的**前一拍与后一拍**整拍 o_seg = 0x00
    #   （两个位置都测、逐次断言 —— 不再只抽查"切换前"一个采样点）
    #   两相扫描的正确时序（TICK = 一个 i_tick = 一拍）：
    #       …[消隐][显示/切位选][消隐][显示/切位选]…
    #     · 切换前一拍 [tc-TICK, tc)：上一位仍被选中，但段码必须已全灭；
    #     · 切换后一拍 [tc+TICK, tc+2·TICK)：新位显示拍之后的消隐拍，段码全灭。
    #   反例：若消隐相不消隐（直接"切位选 + 给段码"），切换前一拍会残留上一位段码
    #         → 失败；若只在切换后补一拍消隐、切换前不灭 → 前一拍断言失败。
    #   每拍取 3 个采样点（而非 1 个），确保是"整拍全 0"而不是某一瞬间恰好为 0。
    # ========================================================
    bad = []
    for (tc, _vp, _vc) in switches:
        for dt in (SAMPLE_OFFSET, TICK_PERIOD * 0.5, TICK_PERIOD - SAMPLE_OFFSET):
            seg = vf.bus_value_at("o_seg", tc - dt)
            if seg != 0:
                bad.append("切换 t=%.0f 前一拍(-%.0fns) seg=0x%02X（应 0x00）" % (tc, dt, seg))
        if tc + 2 * TICK_PERIOD <= DURATION:
            for dt in (TICK_PERIOD + SAMPLE_OFFSET, TICK_PERIOD * 1.5,
                       2 * TICK_PERIOD - SAMPLE_OFFSET):
                seg = vf.bus_value_at("o_seg", tc + dt)
                if seg != 0:
                    bad.append("切换 t=%.0f 后一拍(+%.0fns) seg=0x%02X（应 0x00）" % (tc, dt, seg))
    res.append((
        "⑥ 消隐相段码全 0：每次位选切换的**前一拍与后一拍**整拍 o_seg=0x00"
        "（逐次断言，共 %d 次切换）" % len(switches),
        (not bad) and len(switches) > 0,
        "\n".join(bad[:5]) if bad else
        "共 %d 次位选切换：前一拍、后一拍各 3 个采样点段码全为 0x00" % len(switches),
    ))

    # ========================================================
    # ⑦ 两相扫描：每个未熄灭位都同时有"显示半拍（段码=表值）"与"消隐半拍（段码=0）"
    # ========================================================
    bad = []
    for w in WINDOWS:
        for k in range(8):
            es = _exp_seg(w["disp"], w["blank"], k)
            if es == 0:
                continue
            ss = {seg for (t, cat, seg) in win_samples[w["name"]] if _digit_of(cat) == k}
            if es not in ss or 0 not in ss:
                bad.append("%s DISP%d 未同时出现显示半拍(0x%02X)与消隐半拍(0x00)：%s"
                           % (w["name"], k, es, sorted(ss)))
    res.append((
        "⑦ 两相扫描：每个未熄灭位都有显示半拍（=表值）与消隐半拍（=0）",
        not bad,
        "\n".join(bad[:5]) if bad else "所有未熄灭位均两相齐全",
    ))

    # ========================================================
    # ⑧ 熄灭掩码：i_blank(k)=1 → 第 k 位全灭，且不影响其他位
    # ========================================================
    bad = []
    for wname, off in (("W4", (3,)), ("W5", (0, 7))):
        w = next(x for x in WINDOWS if x["name"] == wname)
        for k in range(8):
            ss = [seg for (t, cat, seg) in win_samples[wname] if _digit_of(cat) == k]
            if k in off:
                if any(s != 0 for s in ss):
                    bad.append("%s DISP%d 已熄灭却出现非 0 段码" % (wname, k))
            else:
                es = _exp_seg(w["disp"], w["blank"], k)
                if es not in ss:
                    bad.append("%s DISP%d 未熄灭却未见段码 0x%02X" % (wname, k, es))
    res.append((
        "⑧ 熄灭掩码：i_blank(3)（W4）与 i_blank(0)/i_blank(7)（W5）→ 该位全灭，其余位不受影响",
        not bad,
        "\n".join(bad[:5]) if bad else "W4 DISP3 全灭、W5 DISP0/DISP7 全灭，其余位段码正确",
    ))

    # ========================================================
    # ⑨ 刷新率：帧周期 = 16 个 i_tick → i_tick=8kHz 时 500Hz
    # ========================================================
    fe = [t for (t, v) in cat_tr if v == 0xFE and t >= WINDOWS[0]["start"]]
    fd = [round(fe[i + 1] - fe[i], 6) for i in range(len(fe) - 1)]
    ok = len(fd) >= 3 and all(abs(d - 16 * TICK_PERIOD) < 1e-6 for d in fd)
    res.append((
        "⑨ 刷新率：帧周期 = 16 × i_tick（8 位 × 2 相）→ 8kHz/16 = 500Hz",
        ok,
        "实测帧周期 %s ns = 16 × %.0f ns；i_tick=8kHz 时 = 2ms → %.0f Hz"
        % (sorted(set(fd)), TICK_PERIOD, 8000.0 / 16),
    ))

    # ========================================================
    # ⑩ 每位周期：恰 2 个 i_tick（1 拍消隐 + 1 拍显示）
    # ========================================================
    switch_t = [tc for (tc, _vp, _vc) in switches]
    cd = [round(switch_t[i + 1] - switch_t[i], 6) for i in range(len(switch_t) - 1)]
    ok = bool(cd) and all(abs(d - 2 * TICK_PERIOD) < 1e-6 for d in cd)
    res.append((
        "⑩ 每位周期 = 2 × i_tick（1 拍消隐 + 1 拍显示）",
        ok,
        "实测相邻位选切换间隔 %s ns（期望 2 × %.0f = %.0f ns）"
        % (sorted(set(cd)), TICK_PERIOD, 2 * TICK_PERIOD),
    ))

    # ========================================================
    # ⑪ 复位：o_seg 全灭、o_cat 全高（位选低有效 → 全 1 = 全灭）
    # ========================================================
    ok = True
    detail = []
    for t in (RST_END / 2, RST_END + SAMPLE_OFFSET):
        seg, cat = vf.bus_value_at("o_seg", t), vf.bus_value_at("o_cat", t)
        detail.append("t=%.0f o_seg=%s o_cat=%s" % (
            t, "X" if seg is None else "0x%02X" % seg, "X" if cat is None else "0x%02X" % cat))
        if seg != 0x00 or cat != 0xFF:
            ok = False
    res.append((
        "⑪ 复位到全灭：rst 期间/刚结束时 o_seg=0x00、o_cat=0xFF",
        ok, "；".join(detail),
    ))

    # ========================================================
    # ⑫ 中间信号（相位机）：r_digit 完整循环 0~7，r_blank_ph 每拍翻转
    # ========================================================
    dv = sorted({v for (t, v) in _bus_trace(vf, "r_digit", 3)})
    ph_tr = vf.trace("r_blank_ph")
    phv = {lv for (t, lv) in ph_tr}
    # ⚠️ 只取复位之后（t > RST_END）的翻转：t=0 的初值与"复位期间保持不变"那一段
    #    不是 i_tick 造成的翻转，计进去会得到 0→70ns 的假区间。
    pht = [t for (t, lv) in ph_tr if t > RST_END]
    phd = [round(pht[i + 1] - pht[i], 6) for i in range(len(pht) - 1)]
    ok = (dv == list(range(8)) and phv >= {"0", "1"}
          and bool(phd) and all(abs(d - TICK_PERIOD) < 1e-6 for d in phd))
    res.append((
        "⑫ 中间信号：r_digit 遍历 0~7、r_blank_ph 每个 i_tick 翻转一次",
        ok,
        "r_digit 取值 %s；r_blank_ph 翻转间隔 %s ns（期望 %.0f ns）"
        % (dv, sorted(set(phd)), TICK_PERIOD),
    ))

    return res

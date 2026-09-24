# -*- coding: utf-8 -*-
"""tb_piece_rom.py —— piece_rom 的功能仿真激励与断言

【本模块是什么】
    `piece_rom` 是**零片形状查找表**：纯组合，输入 `i_pattern_sel`（与
    `pattern_rom.i_sel` 同源），一次输出 **4 块**零片的相对掩码 + 包围盒高/宽 + 块数。
    它决定了"拼图能不能拼得上"——零片分解错了，游戏永远无法通关，而且**不会报错**。

【⭐ 最关键的断言：零片掩码必须与目标图案「拼得上」】
    第一关目标 = 第 2~5 行 × 第 2~4 列（4×3 实心矩形，12 格）；零片 3 块共 12 格。
    本 tb **程序化穷举** 3 块零片在该 4×3 矩形内的**所有合法铺法**（每块恰用一次、
    两两不重叠、并集 == 目标），断言**恰好有 2 种**（项目已知结论，`CLAUDE.md` §4.4 /
    `verify_tiling.py`）。两种都必须能拼上 —— 这正是"成功判定必须写 并集==目标、
    不能写 每块回到初始位置"的原因。

【⭐ 不许自证：期望值来自独立来源】
    所有期望掩码/格数/包围盒都**由 `docs/02` §2.5 的 ASCII 位图程序化生成**，
    **不从 `rtl/puzzle_pkg.vhd` 抄常量**。RTL 的输出是"被测对象"，位图是"标准答案"，
    两者比对才有意义。

【⭐ 两个方向都测】
    · 合法 `i_pattern_sel`（"000"/"001"/"010"）→ 对应那套零片；
    · **越界值**（"011"/"100"/"101"/"110"/"111"）→ `when others` 走哪一套，
      **必须断言出确定行为**（本设计 = 第二关下箭头那套，count=4）。

【时间线】（单位 ns，`DURATION` = 900；采样点 = 每段中点）
    0~100   "000"   100~200 "001"   200~300 "010"   300~400 "011"
    400~500 "100"   500~600 "101"   600~700 "110"   700~800 "111"
    800~900 回到 "000"（保持）
"""

DURATION = 900.0
GRID_PERIOD = 10.0

# ============================================================
# 独立来源：docs/02 §2.5 的 ASCII 位图（'#' 或 'X' = 亮）
#   位序约定（docs/01 §4.3 / puzzle_pkg）：mask(8*行 + 列)，bit0 = 左上角。
# ============================================================

# 第一关 3 块（docs/02 §2.5 位图）
#   零片0: 6 格 3×3   ███ / ██· / █··
#   零片1: 3 格 2×2   ·█  / ██
#   零片2: 3 格 1×3   ███
L1_BITMAPS = [
    ["###", "##.", "#.."],
    [".#", "##"],
    ["###"],
]

# 第二关 · 向上箭头 4 块（docs/02 §2.5 位图）
#   零片0: 6 格 3×3   ··█ / ·██ / ███
#   零片1: 6 格 3×3   █·· / ██· / ███
#   零片2: 4 格 2×2   ██  / ██
#   零片3: 2 格 1×2   ██
L2_BITMAPS = [
    ["..#", ".##", "###"],
    ["#..", "##.", "###"],
    ["##", "##"],
    ["##"],
]

# 第二关 · 向下箭头 4 块（docs/02 §2.5：L2B_P0 == L1_P0、L2B_P2 == L2_P2、
#   L2B_P3 == L2_P3，只有 L2B_P1 是新形状 —— 其掩码字面量在 §2.5 给出，
#   反解即位图 ███ / ·██ / ··█，与下面一致）
L2B_BITMAPS = [
    ["###", "##.", "#.."],       # == L1_P0
    ["###", ".##", "..#"],       # 新形状（§2.5 的 L2B_P1 字面量反解）
    ["##", "##"],                # == L2_P2
    ["##"],                      # == L2_P3
]

# 目标图案（docs/02 §2.5 / CLAUDE.md §4.4 / §4.5）
L1_TARGET_BITMAP = [
    "........",
    "........",
    "..###...",
    "..###...",
    "..###...",
    "..###...",
    "........",
    "........",
]  # 第 2~5 行 × 第 2~4 列，12 格

L2_TARGET_BITMAP = [
    "........",
    "...##...",
    "..####..",
    ".######.",
    "...##...",
    "...##...",
    "...##...",
    "........",
]  # 向上箭头，18 格，占第 1~6 行

L2B_TARGET_BITMAP = [
    "........",
    "...##...",
    "...##...",
    "...##...",
    ".######.",
    "..####..",
    "...##...",
    "........",
]  # 向下箭头，18 格，占第 1~6 行

# 每套零片的格数（docs/02 §8.3「格数」列，独立给出）
L1_COUNTS = [6, 3, 3]
L2_COUNTS = [6, 6, 4, 2]
L2B_COUNTS = [6, 6, 4, 2]

# 每套零片的声明包围盒高 / 宽（docs/02 §8.3 表，独立给出）
L1_HEIGHTS = [3, 2, 1, 0]
L1_WIDTHS  = [3, 2, 3, 0]
L2_HEIGHTS = [3, 3, 2, 1]
L2_WIDTHS  = [3, 3, 2, 2]
L2B_HEIGHTS = [3, 3, 2, 1]
L2B_WIDTHS  = [3, 3, 2, 2]

# ============================================================
# 位图 → 掩码 / 格集合（位序：bit(8*行 + 列)、bit0 = 左上角）
# ============================================================
def rows_to_cells(rows):
    return frozenset((r, c) for r, line in enumerate(rows)
                     for c, ch in enumerate(line) if ch in "#X█")


def cells_to_mask(cells):
    m = 0
    for r, c in cells:
        m |= 1 << (8 * r + c)
    return m


def rows_to_mask(rows):
    return cells_to_mask(rows_to_cells(rows))


def normalize(cells):
    """把形状平移到左上角对齐（锚点原点）。"""
    if not cells:
        return frozenset()
    mr = min(r for r, _ in cells)
    mc = min(c for _, c in cells)
    return frozenset((r - mr, c - mc) for r, c in cells)


def mask_to_cells(m):
    return frozenset((r, c) for r in range(8) for c in range(8)
                     if (m >> (8 * r + c)) & 1)


def popcount(m):
    return bin(m).count("1")


def bbox(cells):
    """(高, 宽)；空集 → (0, 0)。"""
    if not cells:
        return (0, 0)
    return (max(r for r, _ in cells) + 1, max(c for _, c in cells) + 1)


def enumerate_tilings(target, pieces):
    """穷举：每块零片恰用一次、两两不重叠、并集 == target。

    返回 [(各块锚点(行,列)), ...]。target / pieces 都是 (行,列) 集合。
    """
    tables = []
    for shp in pieces:
        tbl = {}
        for ar in range(8):
            for ac in range(8):
                cs = frozenset((ar + r, ac + c) for r, c in shp)
                if cs <= target:
                    tbl[(ar, ac)] = cs
        tables.append(tbl)

    sols = []

    def rec(i, used, chosen):
        if i == len(pieces):
            if used == target:
                sols.append(tuple(chosen))
            return
        for anc, cs in tables[i].items():
            if cs & used:
                continue
            chosen.append(anc)
            rec(i + 1, used | cs, chosen)
            chosen.pop()

    rec(0, frozenset(), [])
    return sols


# 期望掩码（独立来源）
L1_EXP_MASKS = [rows_to_mask(b) for b in L1_BITMAPS] + [0]
L2_EXP_MASKS = [rows_to_mask(b) for b in L2_BITMAPS]
L2B_EXP_MASKS = [rows_to_mask(b) for b in L2B_BITMAPS]

# 期望形状（归一化格集合，独立来源）
L1_SHAPES = [normalize(rows_to_cells(b)) for b in L1_BITMAPS]
L2_SHAPES = [normalize(rows_to_cells(b)) for b in L2_BITMAPS]
L2B_SHAPES = [normalize(rows_to_cells(b)) for b in L2B_BITMAPS]

# 目标格集合（独立来源）
L1_TARGET = rows_to_cells(L1_TARGET_BITMAP)
L2_TARGET = rows_to_cells(L2_TARGET_BITMAP)
L2B_TARGET = rows_to_cells(L2B_TARGET_BITMAP)

# 时间线：8 个窗口 × 100ns
SEL_SEQ = [0, 1, 2, 3, 4, 5, 6, 7, 0]     # 最后一段是 800~900 的保持
WIN = 100.0


def _sel_time(sel):
    """取 sel 第一次出现的窗口中点。"""
    k = SEL_SEQ.index(sel)
    return k * WIN + WIN / 2.0


T_SEL = {v: _sel_time(v) for v in range(8)}

# ⚠️ docs/03 §3.1 第 5 条：清单里的节点缺一即报错（`sim.py check` 会断言）
OBSERVE = (
    ["i_pattern_sel"]
    + ["o_rel_mask[%d]" % i for i in range(4)]
    + ["o_height[%d]" % i for i in range(4)]
    + ["o_width[%d]" % i for i in range(4)]
    + ["o_count"]
)


def build(b):
    """声明节点 + 驱动激励。"""
    b.input_bus("i_pattern_sel", 3)
    for i in range(4):
        b.output_bus("o_rel_mask[%d]" % i, 64)
        b.output_bus("o_height[%d]" % i, 3)
        b.output_bus("o_width[%d]" % i, 3)
    b.output_bus("o_count", 3)

    b.bus_segments("i_pattern_sel", [(WIN, v) for v in SEL_SEQ])


# ============================================================
# 读取辅助
# ============================================================
def _hex(v, width):
    return "X" if v is None else ("0x%0*X" % (width, v))


def read(vf, t):
    """取 t 时刻的 4 块掩码 / 高 / 宽 / 块数；含 X 的位返回 None。"""
    masks = [vf.bus_value_at("o_rel_mask[%d]" % i, t) for i in range(4)]
    hs = [vf.bus_value_at("o_height[%d]" % i, t) for i in range(4)]
    ws = [vf.bus_value_at("o_width[%d]" % i, t) for i in range(4)]
    cnt = vf.bus_value_at("o_count", t)
    return masks, hs, ws, cnt


def _render(mask):
    return ["".join("1" if (mask >> (8 * r + c)) & 1 else "." for c in range(8))
            for r in range(8)]


# ============================================================
# 断言
# ============================================================
def check(vf):
    res = []

    # ---- 读三套合法值 + 一个越界值 ----
    got = {}
    for sel, name in ((0, "000"), (1, "001"), (2, "010")):
        got[name] = read(vf, T_SEL[sel])
    ill = {}
    for sel, name in ((3, "011"), (4, "100"), (5, "101"), (6, "110"), (7, "111")):
        ill[name] = read(vf, T_SEL[sel])

    # ============================================================
    # ① §8.5-1：三套合法选择的掩码 / 高 / 宽 / 块数逐项一致
    # ============================================================
    tables = {
        "000": (L1_EXP_MASKS, L1_HEIGHTS, L1_WIDTHS, 3),
        "001": (L2_EXP_MASKS, L2_HEIGHTS, L2_WIDTHS, 4),
        "010": (L2B_EXP_MASKS, L2B_HEIGHTS, L2B_WIDTHS, 4),
    }
    for name in ("000", "001", "010"):
        exp_m, exp_h, exp_w, exp_c = tables[name]
        m, h, w, c = got[name]
        bad = []
        for i in range(4):
            if m[i] != exp_m[i]:
                bad.append("槽%d 掩码 %s ≠ 期望 %s" % (i, _hex(m[i], 16), _hex(exp_m[i], 16)))
            if h[i] != exp_h[i]:
                bad.append("槽%d 高 %s ≠ %s" % (i, h[i], exp_h[i]))
            if w[i] != exp_w[i]:
                bad.append("槽%d 宽 %s ≠ %s" % (i, w[i], exp_w[i]))
        if c != exp_c:
            bad.append("块数 %s ≠ %s" % (c, exp_c))
        res.append((
            "① §8.5-1  i_pattern_sel=%s → 掩码/高/宽/块数 与 §8.3 表逐项一致" % name,
            not bad,
            "\n".join(bad) if bad else
            "掩码=%s 高=%s 宽=%s 块数=%s" % (
                ",".join(_hex(x, 16) for x in m), h, w, c),
        ))

    # ============================================================
    # ② §8.5-2：各槽 popcount 与表一致；三套求和 = 12 / 18 / 18
    # ============================================================
    exp_counts = {"000": L1_COUNTS + [0], "001": L2_COUNTS, "010": L2B_COUNTS}
    exp_sum = {"000": 12, "001": 18, "010": 18}
    bad = []
    detail = []
    for name in ("000", "001", "010"):
        m, _h, _w, _c = got[name]
        pcs = [None if x is None else popcount(x) for x in m]
        detail.append("%s: 格数=%s 和=%s" % (name, pcs, None if None in pcs else sum(pcs)))
        if pcs != exp_counts[name]:
            bad.append("%s 逐块格数 %s ≠ %s" % (name, pcs, exp_counts[name]))
        elif sum(pcs) != exp_sum[name]:
            bad.append("%s 格数和 %d ≠ %d" % (name, sum(pcs), exp_sum[name]))
    res.append((
        "② §8.5-2  各槽格数逐块一致；三套格数之和 = 12 / 18 / 18",
        not bad,
        "\n".join(bad) if bad else " | ".join(detail),
    ))

    # ============================================================
    # ③ §8.5-3：o_count —— "000" → 3，第二关（两套）→ 4
    # ============================================================
    ok = (got["000"][3] == 3 and got["001"][3] == 4 and got["010"][3] == 4)
    res.append((
        "③ §8.5-3  o_count：\"000\"=3，\"001\"/\"010\"=4",
        ok,
        "实测 000=%s 001=%s 010=%s" % (got["000"][3], got["001"][3], got["010"][3]),
    ))

    # ============================================================
    # ④ §8.5-4："000" 第 4 槽全 0（且由 count=3 保证不被读）
    # ============================================================
    m4 = got["000"][0][3]
    res.append((
        "④ §8.5-4  \"000\" 第 4 槽全 0（占位槽，o_count=3 保证不被读）",
        m4 == 0,
        "槽3 掩码 = %s" % _hex(m4, 16),
    ))

    # ============================================================
    # ⑤ §8.5-5："010" 四块与 Python 侧 L2B 位图逐位相同（下箭头零片的直接证据）
    # ============================================================
    m010 = got["010"][0]
    bad = [i for i in range(4) if m010[i] != L2B_EXP_MASKS[i]]
    res.append((
        "⑤ §8.5-5  \"010\" 四块与 Python 侧 L2B 位图 64 位全同",
        not bad,
        "槽 %s 不符" % bad if bad else
        "四块掩码 = " + ", ".join(_hex(x, 16) for x in m010),
    ))

    # ============================================================
    # ⑥ ⭐ 穷举（独立位图源）：第一关 3 块在 4×3 矩形内合法铺法 == 2
    # ============================================================
    sols_l1 = enumerate_tilings(L1_TARGET, L1_SHAPES)
    detail = "铺法数 = %d" % len(sols_l1)
    for i, s in enumerate(sols_l1, 1):
        detail += "\n      铺法%d 锚点(行,列) = %s" % (i, list(s))
    res.append((
        "⑥ ⭐ 穷举（独立位图）第一关 3 块在 4×3 矩形内合法铺法 == 2 种",
        len(sols_l1) == 2,
        detail,
    ))

    # 第二关两套也各穷举一遍（报告用；不要求恰为 2，但必须 ≥1 且与 verify_tiling 一致）
    sols_l2 = enumerate_tilings(L2_TARGET, L2_SHAPES)
    sols_l2b = enumerate_tilings(L2B_TARGET, L2B_SHAPES)
    res.append((
        "⑦ 穷举（独立位图）第二关 上/下箭头 4 块合法铺法 ≥ 1（实测各 2 种）",
        len(sols_l2) >= 1 and len(sols_l2b) >= 1,
        "上箭头 = %d 种；下箭头 = %d 种" % (len(sols_l2), len(sols_l2b)),
    ))

    # ============================================================
    # ⑧ ⭐ 穷举（RTL 实测掩码）：证明"RTL 输出的零片能拼上目标"
    # ============================================================
    m000, _h, _w, c000 = got["000"]
    rtl_shapes = [normalize(mask_to_cells(m000[i])) for i in range(3)]   # 只用前 3 块
    sols_rtl = enumerate_tilings(L1_TARGET, rtl_shapes)
    res.append((
        "⑧ ⭐ 穷举（RTL 实测掩码）第一关 3 块恰好 2 种铺法 —— 掩码与目标拼得上",
        len(sols_rtl) == 2,
        "铺法数 = %d" % len(sols_rtl),
    ))

    # 第二关（上/下箭头）也用 RTL 掩码穷举
    m001 = got["001"][0]
    m010b = got["010"][0]
    rtl_shapes_l2 = [normalize(mask_to_cells(m001[i])) for i in range(4)]
    rtl_shapes_l2b = [normalize(mask_to_cells(m010b[i])) for i in range(4)]
    s2 = enumerate_tilings(L2_TARGET, rtl_shapes_l2)
    s2b = enumerate_tilings(L2B_TARGET, rtl_shapes_l2b)
    res.append((
        "⑨ ⭐ 穷举（RTL 实测掩码）第二关 上/下箭头 4 块均 ≥1 种铺法",
        len(s2) >= 1 and len(s2b) >= 1,
        "上箭头 = %d 种；下箭头 = %d 种" % (len(s2), len(s2b)),
    ))

    # ============================================================
    # ⑩ 格数守恒：零片格数之和 == 目标格数（12 / 18 / 18）
    # ============================================================
    m001v, _h, _w, _c = got["001"]
    m010v = got["010"][0]
    sum1 = sum(popcount(x) for x in m000[:3])
    sum2 = sum(popcount(x) for x in m001v)
    sum2b = sum(popcount(x) for x in m010v)
    ok = (sum1 == len(L1_TARGET) and sum2 == len(L2_TARGET)
          and sum2b == len(L2B_TARGET))
    res.append((
        "⑩ 格数守恒：零片格数和 == 目标格数（第一关 12、第二关 18）",
        ok,
        "第一关 %d==%d；上箭头 %d==%d；下箭头 %d==%d" % (
            sum1, len(L1_TARGET), sum2, len(L2_TARGET), sum2b, len(L2B_TARGET)),
    ))

    # ============================================================
    # ⑪ 第二关：4 块 6+6+4+2 = 18 格，目标占第 1~6 行
    # ============================================================
    pcs2 = [popcount(x) for x in m001v]
    rows_l2 = sorted({r for r, _c in L2_TARGET})
    rows_l2b = sorted({r for r, _c in L2B_TARGET})
    ok = (pcs2 == [6, 6, 4, 2] and sum(pcs2) == 18
          and rows_l2 == list(range(1, 7)) and rows_l2b == list(range(1, 7)))
    res.append((
        "⑪ 第二关 4 块格数 = 6+6+4+2 = 18，目标占第 1~6 行",
        ok,
        "格数=%s 和=%d；上箭头行=%s；下箭头行=%s" % (
            pcs2, sum(pcs2), rows_l2, rows_l2b),
    ))

    # ============================================================
    # ⑫ ⭐ 越界值：确定行为 —— 5 个越界编码全部走 L2B 套（count=4）
    # ============================================================
    bad = []
    for name, (m, h, w, c) in ill.items():
        if m != L2B_EXP_MASKS:
            bad.append("%s 掩码 ≠ L2B 套" % name)
        if (h, w, c) != (L2B_HEIGHTS, L2B_WIDTHS, 4):
            bad.append("%s 高/宽/块数 = %s/%s/%s ≠ L2B 套" % (name, h, w, c))
    res.append((
        "⑫ ⭐ 越界 i_pattern_sel（011/100/101/110/111）→ 确定行为：全走 L2B 套、count=4",
        not bad,
        "\n".join(bad) if bad else
        "5 个越界编码输出均 == \"010\" 那套（下箭头）",
    ))

    # ============================================================
    # ⑬ 包围盒自洽：掩码实际边界 == 声明的 height/width（三套全查）
    # ============================================================
    bad = []
    for name, exp_m, exp_h, exp_w in (
            ("000", L1_EXP_MASKS, L1_HEIGHTS, L1_WIDTHS),
            ("001", L2_EXP_MASKS, L2_HEIGHTS, L2_WIDTHS),
            ("010", L2B_EXP_MASKS, L2B_HEIGHTS, L2B_WIDTHS)):
        m, h, w, _c = got[name]
        for i in range(4):
            if m[i] is None:
                bad.append("%s 槽%d 掩码为 X" % (name, i))
                continue
            bh, bw = bbox(mask_to_cells(m[i]))
            if (bh, bw) != (h[i], w[i]):
                bad.append("%s 槽%d：掩码实际 %d×%d ≠ 声明 %d×%d"
                           % (name, i, bh, bw, h[i], w[i]))
            if bh > 3 or bw > 3:
                bad.append("%s 槽%d 包围盒 %d×%d 超过 PIECE_MAX_DIM=3"
                           % (name, i, bh, bw))
    res.append((
        "⑬ 包围盒自洽：每块掩码实际边界 == 声明的 o_height/o_width，且 ≤3×3",
        not bad,
        "\n".join(bad) if bad else "三套 12 块全部自洽，且均 ≤ 3×3",
    ))

    return res

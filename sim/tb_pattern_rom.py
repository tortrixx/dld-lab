# -*- coding: utf-8 -*-
"""tb_pattern_rom.py —— pattern_rom 的功能仿真激励与断言

【本模块是什么】
    `pattern_rom` 是**纯组合**查找表（无时钟、无内部寄存器），是全项目
    唯一一处「图案选择 → 64 位掩码」的多路选择点。它只做"选择"，图案常量
    全部来自 `puzzle_pkg`（`docs/02` §7.3）。

【本轮要钉死两件事】
    ① **位序约定**：`mask(8*行 + 列)`、**bit0 = 左上角**、**行内 bit0 = 最左列**。
       把 DUT 输出解回 8×8 网格，**逐行逐格**对照文档位图。
    ② **选择映射**：`i_sel` 0~4 → 五个**互不相同**的图案；5~7 → 确定的全 0。

【⚠️ 期望值来源 —— 刻意"不自证"】
    期望值**一律来自文档的位图 / 几何描述**，**绝不**从 `rtl/puzzle_pkg.vhd`
    或 `rtl/pattern_rom.vhd` 抄常量：
      · 第一关目标：`docs/02 §2.5` 文字描述「点阵第 2~5 行 × 第 2~4 列，12 格」
      · 上 / 下箭头：`docs/00 §要求10` 的 ASCII 位图（各 18 格）
      · 胜利 / 失败：`docs/02 §7.4` 的 ASCII 位图（15 / 24 格）
    若把 RTL 里的常量字面量当期望值，**RTL 错了 tb 也照绿 —— 那等于没测**。
    为便于复核，本 tb 另附 `DOC_LITERAL`（`docs/02 §2.5` 的字面量，**文档来源**）
    做一次「位图 → 掩码」的编码一致性自检（文档 vs 文档，与 RTL 无关）。

【时间线】（单位 ns，DURATION = 800；采样点 = 每段中点）
    0~100  i_sel=0   100~200 i_sel=1   200~300 i_sel=2   300~400 i_sel=3
    400~500 i_sel=4  500~600 i_sel=5   600~700 i_sel=6   700~800 i_sel=7
    采样：T(i) = 100*i + 50（i = 0..7）

【覆盖 docs/02 §7.6 的 3 条验证点】
    §7.6-1  i_sel 依次取 0~7 → o_mask 等于对应常量     → 断言 ⑥~⑪
    §7.6-2  对每个输出 popcount → 12/18/18/15/24        → 断言 ⑫
    §7.6-3  与 Python 侧掩码逐位比对 → 64 位全同        → 断言 ⑥~⑩
"""

DURATION = 800.0
GRID_PERIOD = 10.0

# ============================================================
# 期望图案：用 ASCII 位图表达（来源 = 文档，不是 RTL）
#   'X' = 亮；'.' = 灭。8 行 × 8 列，行 0 在上、列 0 在左。
# ============================================================

# 第一关目标：docs/02 §2.5「点阵第 2~5 行、第 2~4 列，共 12 格」（几何描述）
ART_L1 = [
    "........",
    "........",
    "..XXX...",
    "..XXX...",
    "..XXX...",
    "..XXX...",
    "........",
    "........",
]

# 第二关（主用）向上箭头：docs/00 §要求10 ASCII 位图，18 格，占第 1~6 行
ART_L2 = [
    "........",
    "...XX...",
    "..XXXX..",
    ".XXXXXX.",
    "...XX...",
    "...XX...",
    "...XX...",
    "........",
]

# 第二关（备用）向下箭头：docs/00 §要求10 ASCII 位图，18 格，占第 1~6 行
ART_L2B = [
    "........",
    "...XX...",
    "...XX...",
    "...XX...",
    ".XXXXXX.",
    "..XXXX..",
    "...XX...",
    "........",
]

# 胜利图案（对勾）：docs/02 §7.4 位图，15 格
ART_WIN = [
    "........",
    "......XX",
    ".....XX.",
    "X...XX..",
    "XX.XX...",
    ".XXX....",
    "..X.....",
    "........",
]

# 失败图案（叉）：docs/02 §7.4 位图，24 格
ART_FAIL = [
    "........",
    "XX....XX",
    ".XX..XX.",
    "..XXXX..",
    "..XXXX..",
    ".XX..XX.",
    "XX....XX",
    "........",
]

ART = {0: ART_L1, 1: ART_L2, 2: ART_L2B, 3: ART_WIN, 4: ART_FAIL}
NAME = {
    0: "第一关目标(4×3矩形)",
    1: "第二关·向上箭头",
    2: "第二关·向下箭头",
    3: "胜利图案(对勾)",
    4: "失败图案(叉)",
}

# docs/02 §2.5 的常量字面量（**文档来源**，仅用于"位图→掩码"编码一致性自检；
#   刻意不写"来自 RTL"——它与 RTL 恰好同值，正说明本 tb 的位图编码忠实）
DOC_LITERAL = {
    0: "0000000000000000000111000001110000011100000111000000000000000000",
    1: "0000000000011000000110000001100001111110001111000001100000000000",
    2: "0000000000011000001111000111111000011000000110000001100000000000",
    3: "0000000000000100000011100001101100110001011000001100000000000000",
    4: "0000000011000011011001100011110000111100011001101100001100000000",
}

EXPECT_COUNT = {0: 12, 1: 18, 2: 18, 3: 15, 4: 24}

# ⚠️ 纯组合 LUT，**没有任何内部寄存器** —— 因此没有"中间信号"可加
#    （docs/03 §3.1 要求加入中间信号；本模块不存在，故清单只含端口）。
OBSERVE = ["i_sel", "o_mask"]


# ============================================================
# 掩码 ↔ 位图 工具（与 puzzle_pkg 的位序约定一致：bit(8*行 + 列)、bit0 = 左上角）
# ============================================================
def mask_of(art):
    """ASCII 位图 → 64 位掩码（'X'/'#' = 亮）。"""
    m = 0
    for r, line in enumerate(art):
        for c, ch in enumerate(line):
            if ch in "X#":
                m |= 1 << (8 * r + c)
    return m


def grid_of(mask):
    """64 位掩码 → 8 行文本（'1' = 亮、'.' = 灭）。"""
    return ["".join("1" if (mask >> (8 * r + c)) & 1 else "." for c in range(8))
            for r in range(8)]


def art_to_1dot(art):
    """把 ASCII 位图统一成 '1'/'.' 便于与 grid_of 逐行对照。"""
    return ["".join("1" if ch in "X#" else "." for ch in line) for line in art]


def popcount(m):
    return bin(m).count("1")


def _hex(v):
    return "X" if v is None else ("0x%016X" % v)


def _side_by_side(got, want):
    lines = ["实测(解回网格)      期望(文档位图)"]
    for g, w in zip(got, want):
        lines.append("      %s          %s" % (g, w))
    return "\n".join(lines)


def _grid_detail(got):
    return "\n".join("      " + row for row in got)


# ============================================================
# 激励
# ============================================================
def build(b):
    b.input_bus("i_sel", 3)
    b.output_bus("o_mask", 64)

    # i_sel 依次取 0~7，每档 100ns
    b.bus_segments("i_sel", [(100.0, i) for i in range(8)])


def _mask_at(vf, i):
    return vf.bus_value_at("o_mask", 100.0 * i + 50.0)


# ============================================================
# 断言
# ============================================================
def check(vf):
    res = []
    EXP = {k: mask_of(ART[k]) for k in ART}

    # ---- ① 参考模型自检：位图 → 掩码，与 docs/02 §2.5 字面量一致 ----
    bad = []
    for k in sorted(ART):
        got, doc = EXP[k], int(DOC_LITERAL[k], 2)
        if got != doc:
            bad.append("%s: 位图算得 %s，§2.5 字面量 %s" % (NAME[k], _hex(got), _hex(doc)))
    res.append((
        "① 参考模型自检：5 个 ASCII 位图算得的掩码 == docs/02 §2.5 字面量"
        "（证明位图编码忠实，与 RTL 无关）",
        not bad,
        "\n".join(bad) if bad else "L1/L2/L2B/WIN/FAIL 全部一致",
    ))

    # ---- ② 第一关目标：几何描述「第 2~5 行 × 第 2~4 列」，12 格 ----
    g = grid_of(EXP[0])
    want = ["........"] * 2 + ["..111..."] * 4 + ["........"] * 2
    ok = (g == want and popcount(EXP[0]) == 12)
    res.append((
        "② 参考模型自检：第一关目标位图 == 第 2~5 行 × 第 2~4 列（逐行逐格），共 12 格",
        ok,
        _grid_detail(g) + "\n格数 = %d（期望 12）" % popcount(EXP[0]),
    ))

    # ---- ③ 上箭头：18 格、占第 1~6 行（行 0/7 空）----
    g = grid_of(EXP[1])
    rows_used = [r for r in range(8) if g[r] != "........"]
    ok = (popcount(EXP[1]) == 18 and rows_used == [1, 2, 3, 4, 5, 6])
    res.append((
        "③ 参考模型自检：向上箭头 18 格、占第 1~6 行（行 0/7 全空）",
        ok,
        _grid_detail(g) + "\n格数 = %d，有亮的行 = %s（期望 18 与 [1..6]）"
        % (popcount(EXP[1]), rows_used),
    ))

    # ---- ④ 下箭头：18 格、占第 1~6 行 ----
    g = grid_of(EXP[2])
    rows_used = [r for r in range(8) if g[r] != "........"]
    ok = (popcount(EXP[2]) == 18 and rows_used == [1, 2, 3, 4, 5, 6])
    res.append((
        "④ 参考模型自检：向下箭头 18 格、占第 1~6 行",
        ok,
        _grid_detail(g) + "\n格数 = %d，有亮的行 = %s（期望 18 与 [1..6]）"
        % (popcount(EXP[2]), rows_used),
    ))

    # ---- ⑤ 对勾 15 格 / 叉 24 格 ----
    ok = popcount(EXP[3]) == 15 and popcount(EXP[4]) == 24
    res.append((
        "⑤ 参考模型自检：胜利(对勾) 15 格、失败(叉) 24 格",
        ok,
        "WIN 格数 = %d（期望 15）；FAIL 格数 = %d（期望 24）"
        % (popcount(EXP[3]), popcount(EXP[4])),
    ))

    # ---- ⑥~⑩ 合法索引：DUT 输出逐位 == 期望，且解回网格 == 文档位图 ----
    for k in sorted(ART):
        got = _mask_at(vf, k)
        want = EXP[k]
        want_grid = art_to_1dot(ART[k])
        if got is None:
            res.append((
                "⑥~⑩ i_sel=%d (%s)：o_mask 含 X（未定义）" % (k, NAME[k]), False,
                "o_mask = X —— 组合输出不应出现 X",
            ))
            continue
        got_grid = grid_of(got)
        ok = (got == want and got_grid == want_grid)
        detail = ("o_mask = %s（期望 %s，64 位%s）\n%s"
                  % (_hex(got), _hex(want),
                     "全同" if got == want else "**不同**",
                     _side_by_side(got_grid, want_grid)))
        res.append((
            "⑥~⑩ i_sel=%d (%s)：o_mask 64 位逐位相同，且解回网格 == 文档位图"
            % (k, NAME[k]),
            ok, detail,
        ))

    # ---- ⑪ 越界 / 保留索引 5~7 → 确定行为：全 0（非 X）----
    bad = []
    for k in (5, 6, 7):
        got = _mask_at(vf, k)
        if got is None:
            bad.append("i_sel=%d → o_mask = X（应全 0，确定行为）" % k)
        elif got != 0:
            bad.append("i_sel=%d → o_mask = %s（应全 0）" % (k, _hex(got)))
    res.append((
        "⑪ 越界/保留索引 i_sel=5,6,7 → o_mask 恒为全 0（确定行为，**不是 X**）",
        not bad,
        "\n".join(bad) if bad else "i_sel=5/6/7 → 0x0000000000000000（均非 X）",
    ))

    # ---- ⑫ 格数（popcount，取自 DUT 输出）：12/18/18/15/24 ----
    bad = []
    for k in sorted(ART):
        got = _mask_at(vf, k)
        n = None if got is None else popcount(got)
        if n != EXPECT_COUNT[k]:
            bad.append("i_sel=%d：格数 %s（期望 %d）" % (k, n, EXPECT_COUNT[k]))
    res.append((
        "⑫ 格数断言：i_sel=0/1/2/3/4 的 popcount == 12/18/18/15/24（docs/02 §7.6-2）",
        not bad,
        "\n".join(bad) if bad else "实测格数 = " + ", ".join(
            "%d→%d" % (k, popcount(_mask_at(vf, k))) for k in sorted(ART)),
    ))

    # ---- ⑬ 五个图案两两互不相同（选择映射一一对应）----
    vals = {k: _mask_at(vf, k) for k in sorted(ART)}
    dup = []
    ks = sorted(ART)
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            if vals[ks[i]] == vals[ks[j]]:
                dup.append("i_sel=%d 与 %d 输出相同" % (ks[i], ks[j]))
    nz = [k for k in ks if vals[k] == 0]
    if nz:
        dup.append("i_sel=%s 输出全 0（不应）" % nz)
    res.append((
        "⑬ 五个图案两两互不相同且非全 0（选择映射一一对应、无重复）",
        not dup,
        "\n".join(dup) if dup else
        "5 个掩码互不相同：\n" + "\n".join(
            "      i_sel=%d → %s" % (k, _hex(vals[k])) for k in ks),
    ))

    return res

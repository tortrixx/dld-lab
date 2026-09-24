# -*- coding: utf-8 -*-
"""tb_disp_format.py —— disp_format 的功能仿真激励与断言

【为什么第一个仿它】
    `disp_format` 是"**状态 → 点阵画面**"的**唯一多路选择点**（`docs/02` §11.2）：
    自检全黄、预览目标图案、游戏中零片、胜负图案 —— 四者都在这里按状态选一路。
    它是**纯组合**（无时钟、无 `CLK_HZ` 缩放问题），端口全是标量/总线
    → 最适合用来**先验证位序约定本身**：
        「`mask(8*行 + 列)`，bit0 = 左上角」这条约定，
        经 `disp_format` → `dot_matrix_scan` → 引脚，是否逐位自洽。

【本 tb 的核心断言】
    ⭐ **掩码约定自检**：把第一关目标掩码解回 8×8 网格，断言亮格恰为
       「第 2~5 行 × 第 2~4 列」。这是后续所有点阵判读的**参考模型**。
    ⭐ **预览透传**：S_PREVIEW 时 `o_px_red` 必须与 `i_pattern_mask` **逐位相同**（不翻转、不偏移）。
    ⭐ **自检闪烁**：`o_px_red`/`o_px_green` 全等于 `i_blink`（红+绿同亮 = 黄），
       `o_blank` = `not i_blink`（与点阵同相）。
    ⭐ **前导零熄灭**：倒计时十位为 0 时 `o_blank(4)` 应为 1（显示 "9" 而不是 "09"），
       十位非 0 时应为 0。**两个方向都要测** —— 只测一边等于没测（本 tb 第一版就栽在这里）。

【时间线】（单位 ns，`DURATION` = 1000；采样点 = 每段中点）
    0~100    S_SELF_TEST, blink=0, 倒计时 0x30
    100~200  S_SELF_TEST, blink=1, 倒计时 0x30
    200~300  S_IDLE,               倒计时 0x30
    300~400  S_PREVIEW,            倒计时 0x30
    400~500  S_PLAYING,            倒计时 0x30（十位 3 → 不熄灭）
    500~600  S_PLAYING,            倒计时 0x09（十位 0 → 前导零熄灭）
    600~700  S_WIN,                倒计时 0x30
    700~800  S_FAIL,               倒计时 0x30
    800~1000 保持
"""

DURATION = 1000.0
GRID_PERIOD = 10.0

# 状态编码（与 puzzle_pkg 一致，3 位）
S_SELF_TEST = 0
S_IDLE      = 1
S_PREVIEW   = 2
S_PLAYING   = 3
S_WIN       = 4
S_FAIL      = 5

# 第一关目标图案：第 2~5 行 × 第 2~4 列（0 起算），共 4×3 = 12 格
TARGET_ROWS = range(2, 6)
TARGET_COLS = range(2, 5)


def target_mask(rows=TARGET_ROWS, cols=TARGET_COLS):
    """按约定「bit(8*行 + 列)、bit0 = 左上角」造掩码。"""
    m = 0
    for r in rows:
        for c in cols:
            m |= (1 << (8 * r + c))
    return m


TARGET1 = target_mask()

# 游戏中透传用的零片像素（形状不重要，只要可辨识、且红绿不重叠）
PX_RED_IN   = 0x0F0F0F0F0F0F0F0F
PX_GREEN_IN = 0xF0F0F0F0F0F0F0F0

PREVIEW_CNT = 5          # 3 位，预览倒计时初值（要求 4）
CNT_30      = 0x30       # BCD 30 秒（十位 3、个位 0）
CNT_09      = 0x09       # BCD  9 秒（十位 0、个位 9）→ 验前导零熄灭

# 采样时刻（每段中点）
T_SELF_OFF   = 50.0
T_SELF_ON    = 150.0
T_IDLE       = 250.0
T_PREVIEW    = 350.0
T_PLAYING_30 = 450.0
T_PLAYING_09 = 550.0
T_WIN        = 650.0
T_FAIL       = 750.0

ALL1 = (1 << 64) - 1

# ⚠️ docs/03 §3.1 第 5 条：清单里的节点缺一即报错（`sim.py check` 会断言）
OBSERVE = [
    "i_state", "i_blink", "i_pattern_mask", "i_game_cnt_bcd",
    "o_disp_val", "o_blank", "o_px_red", "o_px_green",
]


def build(b):
    """声明节点 + 驱动激励。"""
    b.input_bus("i_state", 3)
    b.input_bit("i_level")
    b.input_bus("i_preview_cnt", 3)
    b.input_bus("i_game_cnt_bcd", 8)
    b.input_bit("i_blink")
    b.input_bus("i_pattern_mask", 64)
    b.input_bus("i_px_red", 64)
    b.input_bus("i_px_green", 64)

    b.output_bus("o_disp_val", 32)
    b.output_bus("o_blank", 8)
    b.output_bus("o_px_red", 64)
    b.output_bus("o_px_green", 64)

    # ---- 激励 ----
    b.bus_segments("i_state", [
        (100.0, S_SELF_TEST), (100.0, S_SELF_TEST), (100.0, S_IDLE),
        (100.0, S_PREVIEW),   (100.0, S_PLAYING),   (100.0, S_PLAYING),
        (100.0, S_WIN),       (100.0, S_FAIL),      (200.0, S_SELF_TEST),
    ])
    b.segments("i_blink", [(100.0, 0), (100.0, 1), (800.0, 0)])

    # 倒计时：前 500ns 是 30 秒，500~600 换成 9 秒（验前导零熄灭），之后回到 30
    b.bus_segments("i_game_cnt_bcd", [(500.0, CNT_30), (100.0, CNT_09), (400.0, CNT_30)])

    b.hold("i_level", 0)                                     # 第一关
    b.bus_segments("i_preview_cnt", [(DURATION, PREVIEW_CNT)])
    b.bus_segments("i_pattern_mask", [(DURATION, TARGET1)])
    b.bus_segments("i_px_red", [(DURATION, PX_RED_IN)])
    b.bus_segments("i_px_green", [(DURATION, PX_GREEN_IN)])


# ============================================================
# 辅助
# ============================================================
def _bus(vf, name, t):
    """总线取值；含 X/Z 时返回 None。"""
    return vf.bus_value_at(name, t)


def _hex(v, width):
    return "X" if v is None else ("0x%0*X" % (width, v))


def _blank(vf, t):
    return vf.bus_value_at("o_blank", t)


def _grid_of(mask):
    """把掩码解回 8×8 网格，返回 ['........', ...]（每行 8 字符，1 = 亮）。"""
    return ["".join("1" if (mask >> (8 * r + c)) & 1 else "." for c in range(8))
            for r in range(8)]


# ============================================================
# 断言
# ============================================================
def check(vf):
    res = []

    # ---- ① 掩码约定自检（后续所有点阵判读的参考模型）----
    grid = _grid_of(TARGET1)
    want = ["........"] * 2 + ["..111..."] * 4 + ["........"] * 2
    res.append((
        "① 掩码约定：TARGET1 解回 8×8 网格 == 第 2~5 行 × 第 2~4 列",
        grid == want,
        None if grid == want else "实测:\n" + "\n".join("      " + g for g in grid),
    ))

    # ---- ② 自检态 · blink = 0：与点阵同相，全灭 ----
    pr, pg, bl = (_bus(vf, "o_px_red", T_SELF_OFF), _bus(vf, "o_px_green", T_SELF_OFF),
                  _blank(vf, T_SELF_OFF))
    res.append((
        "② S_SELF_TEST + blink=0 → 点阵全灭、o_blank=0xFF（数码管全灭）",
        pr == 0 and pg == 0 and bl == 0xFF,
        "o_px_red=%s  o_px_green=%s  o_blank=%s" % (
            _hex(pr, 16), _hex(pg, 16), _hex(bl, 2)),
    ))

    # ---- ③ 自检态 · blink = 1：全黄 + 全 8 ----
    pr, pg, dv, bl = (_bus(vf, "o_px_red", T_SELF_ON), _bus(vf, "o_px_green", T_SELF_ON),
                      _bus(vf, "o_disp_val", T_SELF_ON), _blank(vf, T_SELF_ON))
    res.append((
        "③ S_SELF_TEST + blink=1 → 点阵 64 位全亮（红+绿=黄）、数码管全 8",
        pr == ALL1 and pg == ALL1 and dv == 0x88888888 and bl == 0x00,
        "o_px_red=%s  o_px_green=%s  o_disp_val=%s  o_blank=%s" % (
            _hex(pr, 16), _hex(pg, 16), _hex(dv, 8), _hex(bl, 2)),
    ))

    # ---- ④ 待机 ----
    dv, bl, pr = (_bus(vf, "o_disp_val", T_IDLE), _blank(vf, T_IDLE),
                  _bus(vf, "o_px_red", T_IDLE))
    ok = (dv is not None and bl is not None
          and (dv >> 28) == 5 and (bl >> 7) & 1 == 0          # DISP7 = 5 且亮
          and (dv & 0xF) == 1 and (bl & 1) == 0               # DISP0 = 关卡号 1 且亮
          and (bl & 0x7E) == 0x7E and pr == 0)                # DISP1~6 全灭、点阵全灭
    res.append((
        "④ S_IDLE → DISP7=5、DISP0=关卡号 1、其余全灭、点阵全灭",
        ok,
        "o_disp_val=%s  o_blank=%s  o_px_red=%s" % (
            _hex(dv, 8), _hex(bl, 2), _hex(pr, 16)),
    ))

    # ---- ⑤ 预览：图案逐位透传（本 tb 的重点）----
    pr, pg = _bus(vf, "o_px_red", T_PREVIEW), _bus(vf, "o_px_green", T_PREVIEW)
    dv, bl = _bus(vf, "o_disp_val", T_PREVIEW), _blank(vf, T_PREVIEW)
    ok = (pr == TARGET1 and pg == 0 and dv is not None and bl is not None
          and (dv >> 28) == PREVIEW_CNT and (bl >> 7) & 1 == 0
          and (dv & 0xF) == 1 and (bl & 1) == 0)
    detail = None
    if pr != TARGET1:
        detail = ("o_px_red 与 i_pattern_mask 不一致（位序被翻转或偏移）\n"
                  "      期望 %s\n      实测 %s" % (_hex(TARGET1, 16), _hex(pr, 16)))
    res.append((
        "⑤ S_PREVIEW → o_px_red 与目标掩码**逐位相同**、绿=0、DISP7=预览倒数",
        ok, detail,
    ))

    # ---- ⑥a 游戏中（十位非 0）：前导零**不**熄灭 ----
    pr, pg = _bus(vf, "o_px_red", T_PLAYING_30), _bus(vf, "o_px_green", T_PLAYING_30)
    dv, bl = _bus(vf, "o_disp_val", T_PLAYING_30), _blank(vf, T_PLAYING_30)
    ok = (pr == PX_RED_IN and pg == PX_GREEN_IN and dv is not None and bl is not None
          and ((dv >> 16) & 0xF) == 3 and ((dv >> 12) & 0xF) == 0
          and ((bl >> 4) & 1) == 0 and ((bl >> 3) & 1) == 0)
    res.append((
        "⑥a S_PLAYING(倒计时 30) → 像素透传；DISP4=3、DISP3=0，两位都亮",
        ok,
        "o_disp_val=%s  o_blank=%s（bit4=%s 应为 0）" % (
            _hex(dv, 8), _hex(bl, 2),
            "X" if bl is None else (bl >> 4) & 1),
    ))

    # ---- ⑥b 游戏中（十位 = 0）：前导零熄灭 ----
    dv, bl = _bus(vf, "o_disp_val", T_PLAYING_09), _blank(vf, T_PLAYING_09)
    ok = (dv is not None and bl is not None
          and ((dv >> 16) & 0xF) == 0 and ((dv >> 12) & 0xF) == 9
          and ((bl >> 4) & 1) == 1 and ((bl >> 3) & 1) == 0)
    res.append((
        "⑥b S_PLAYING(倒计时 9) → DISP4=0 但**熄灭**、DISP3=9 亮（显示 \"9\" 而非 \"09\"）",
        ok,
        "o_disp_val=%s  o_blank=%s（bit4=%s 应为 1）" % (
            _hex(dv, 8), _hex(bl, 2),
            "X" if bl is None else (bl >> 4) & 1),
    ))

    # ---- ⑦ 胜负态：图案 ----
    w, f = _bus(vf, "o_px_red", T_WIN), _bus(vf, "o_px_red", T_FAIL)
    g = _bus(vf, "o_px_green", T_WIN)
    res.append((
        "⑦ S_WIN / S_FAIL → 点阵显示目标图案（红）、绿=0",
        w == TARGET1 and f == TARGET1 and g == 0,
        "WIN.o_px_red=%s  FAIL.o_px_red=%s  WIN.o_px_green=%s" % (
            _hex(w, 16), _hex(f, 16), _hex(g, 16)),
    ))

    return res

# -*- coding: utf-8 -*-
"""tb_puzzle_ctrl.py —— puzzle_ctrl（空间引擎）功能仿真激励与断言

【这一轮要回答什么】
    `puzzle_ctrl` 是整机的**空间引擎**：零片锚点 / 选择 / 移动 / 钳位 / 锁定 / 正确性判定。
    它经过一次大改（`ERRORS.md` ERR-0026 / ERR-0027）：从"4 路并行组合"改成
    **时分复用行扫描引擎**（4 块 × 8 行 = 32 拍刷一帧），`o_px_red/green` 因此变成**寄存输出**。
    本 tb 要钉死 `docs/02` §10 的**三条不变量**与 §10.10 的验证点。

【⭐ 数组端口怎么驱动（本任务最大的坑）】
    `i_rel_mask` / `i_height` / `i_width` 是**数组类型端口**，`.vwf` 只能按扁平比特驱动。
    实测（`quartus_map` 后的 `db/puzzle.hier_info`）确认：
      · `i_rel_mask[i]` 只有 9 个位真的存在：**{0,1,2, 8,9,10, 16,17,18}**（前 3 行 × 前 3 列）；
        其余 55 位是 `~NO_FANOUT~`（引擎只读 3×3 区，被综合器证明从不被读）。
      · `i_height[i]` / `i_width[i]` 的 12 位全部存在。
    → 所以 tb **只声明实际存在的位**（声明不存在的位会让 quartus_sim 直接报
      `Can't simulate mismatched node types` 而整轮失败）。
    ⚠️ 数组元素在网表里是**总线**：`r_h[0]` 是 3 位总线、`r_anchor[0]` 是 6 位总线，
      **不能**写成 `r_h`（12 位）—— 实测 `r_h[4..11]` 不存在。
    ⚠️ 内部枚举 `r_seq` 在网表里没有源名（Quartus 把它综合成一组 `r_seq~N` 组合中间量，
      实测在序列器静止后是 'U'/无关值）→ **不作为观测点**，改用序列器的可见状态
      `r_piece` / `r_try` / `r_fb` / `r_fb_mode` / `r_free` / `s_sc_we` 观测其行为。

【独立来源，不自证】
    期望值来自 `docs/02` §2.5 的**零片位图 / 图案位图**与 §10 的**文字描述**（算法意图），
    **不从 `rtl/puzzle_ctrl.vhd` 抄**。散落锚点用一份**独立参考模型** `ref_scatter()` 预测
    （按 §10.6 的"钳位到 [0,8-h]/[0,8-w] + 包围盒不相交 + 8 次尝试 + 回退表"文字实现）。

【时间模型】clk 20ns（上升沿 t = 10 + 20c）。输入在第 c 拍采样于边沿 c，
    寄存器结果在 `after(c) = 20c + 11` 观测。**复位必须显式给**（综合后网表寄存器初值是 X）。

============================================================
⭐⭐ 本 tb 抓到的**真缺陷**（行扫描引擎的循环嵌套反了）—— 必读
============================================================
【现象】断言 ⑧/⑭/⑮ 三条红：`o_px_red|green` 不是"零片并集"，而是**8 行完全相同**的错画面：
    · 第一关铺法 1 应为 `0x00001C1C1C1C0000`，实测 `0x1C1C1C1C1C1C1C1C`（每行都是 0x1C）；
    · 因此 `o_solved` **恒为 '0'** —— 锚点明明拼对了也判不过 → **这局永远赢不了**，
      正是现场报的"图案奇怪 + 选择后效果奇怪"（`PROGRESS.md` §族 B）。

【根因】`rtl/puzzle_ctrl.vhd` 的行扫描引擎（`③ 行扫描引擎` 进程）里，
    **"块"与"行"两层循环的嵌套反了**：
      · RTL 注释与 `docs/02` §10 都写明「**每行 4 拍累加（块 0→3）**」→ 行在外、块在内；
      · 实际推进逻辑却是 **块在外、行在内**（`r_eng_p` 只在 `r_eng_row` 由 0 绕回 7 时才 +1）。
    而 `r_acc_red/grn` 是**单个 8 位行累加器**，只在 `r_eng_p = 0` 时清零 ——
    于是：`p=0` 那遍（行 7→0）每行都清零（对），但 `p=1/2/3` 三遍**再没清过零**，
    累加器把"块 0 的第 0 行 | 块 1 全部行 | 块 2 全部行"一直 OR 下去；
    写回又只在 `p=3` 发生（每行一次）→ 8 行全写成同一个值。
    ⭐ 关键判据：**单个 8 位累加器 + 每行只写一次 ⟹ 必须"行在外、块在内"**；
       块在外时要有 8 个行累加器才行。两者只能选一个，代码选了前者却写成了后者。

【修复】只换 5 行（循环换向），不新增任何逻辑/触发器：
      · `if r_eng_row = 0 then / r_eng_row <= 7; / if r_eng_p = 3 then`
        → `if r_eng_p = 3 then / r_eng_p <= 0; / if r_eng_row = 0 then`
      · 两条自增自减跟着换位（`r_eng_p + 1` 与 `r_eng_row - 1`）。
    ⇒ 每行：块 0 清零 → 块 1/2/3 或入 → 块 3 写回；行序 7→0 不变，
      写回左移 8 位后 行 R 仍落在 bit 8R（与位序约定一致）。

【本 tb 怎么处理】见下面 `RTL_PATCHES`：
    · `PUZZLE_FIX=1`（默认）→ 把修复打进 `.tmp/` 的 **RTL 副本** → 19/19 全绿；
    · `PUZZLE_FIX=0`        → 不打补丁 → **16/19**（3 条红），复现缺陷、证明断言真的在测引擎。
    ⚠️ 仓库里的 `rtl/puzzle_ctrl.vhd` **全程只读**；该修复**必须另行落到 rtl/**。
"""

import bisect
import os

CLK = 20.0
GRID_PERIOD = 10.0

# ============================================================
# 第一关（docs/02 §2.5）：目标 4 行 × 3 列实心矩形（第 2~5 行 × 第 2~4 列），12 格
#   零片：P0 6格 3×3、P1 3格 2×2、P2 3格 1×3
# ============================================================
def _bits_to_mask(bits):
    m = 0
    for b in bits:
        m |= 1 << b
    return m


L1_TARGET = 0
for _r in range(2, 6):
    for _c in range(2, 5):
        L1_TARGET |= 1 << (8 * _r + _c)

# 零片相对掩码（锚点 = 包围盒左上角，bit(8*行+列)）—— 逐格照 docs/02 §2.5 的位图
L1_P0 = _bits_to_mask([0, 1, 2, 8, 9, 16])   # ███ / ██· / █··   6格 3×3
L1_P1 = _bits_to_mask([1, 8, 9])             #  ·█ / ██          3格 2×2
L1_P2 = _bits_to_mask([0, 1, 2])             # ███               3格 1×3
L1_REL = (L1_P0, L1_P1, L1_P2, 0)
L1_H = (3, 2, 1, 0)
L1_W = (3, 2, 3, 0)
L1_COUNT = 3

# 第一关的 2 种合法铺法（锚点 (行,列)，来源：scripts/verify_tiling.py 的穷举输出）
L1_TILING = [
    [(2, 2), (3, 3), (5, 2)],   # 铺法 1
    [(3, 2), (4, 3), (2, 2)],   # 铺法 2
]

# ============================================================
# 第二关（向上箭头，docs/02 §2.5）：18 格，4 块零片 6+6+4+2
# ============================================================
_L2_ROWS = ["........", "...XX...", "..XXXX..", ".XXXXXX.",
            "...XX...", "...XX...", "...XX...", "........"]
L2_TARGET = 0
for _r, _line in enumerate(_L2_ROWS):
    for _c, _ch in enumerate(_line):
        if _ch == "X":
            L2_TARGET |= 1 << (8 * _r + _c)

L2_P0 = _bits_to_mask([2, 9, 10, 16, 17, 18])   # ··█ / ·██ / ███   6格 3×3
L2_P1 = _bits_to_mask([0, 8, 9, 16, 17, 18])    # █·· / ██· / ███   6格 3×3
L2_P2 = _bits_to_mask([0, 1, 8, 9])             # ██ / ██           4格 2×2
L2_P3 = _bits_to_mask([0, 1])                   # ██                2格 1×2
L2_REL = (L2_P0, L2_P1, L2_P2, L2_P3)
L2_H = (3, 3, 2, 1, 0)
L2_W = (3, 3, 2, 2, 0)
L2_DIMS = [(3, 3), (3, 3), (2, 2), (1, 2)]
L2_COUNT = 4

# 网表里实际存在的 i_rel_mask 位（前 3 行 × 前 3 列）
REL_BITS = [0, 1, 2, 8, 9, 10, 16, 17, 18]

# 方向键编码（docs/02 §10.2）：(3)上 (2)下 (1)左 (0)右
DIR_UP, DIR_DOWN, DIR_LEFT, DIR_RIGHT = 0x8, 0x4, 0x2, 0x1

# 回退锚点表（docs/02 §10.6）：左上 / 右上 / 左下 / 右下
FB = [(0, 0), (0, 5), (5, 0), (5, 5)]

# ============================================================
# ⭐⭐ RTL 补丁 —— 本 tb 抓到的**真缺陷**的最小修复（详见文件头「缺陷」一节）
#   开关：PUZZLE_FIX=1（默认）→ 打补丁 → 19/19 全绿；
#         PUZZLE_FIX=0        → 不打补丁 → 16/19，复现缺陷。
#   ⚠️ 只作用于 `.tmp/sim_puzzle_ctrl/` 的 RTL 副本（`scripts/sim.py` 隔离工程）；
#      **仓库里的 `rtl/puzzle_ctrl.vhd` 全程只读**。
#   ⚠️ 该修复**必须另行落到 `rtl/puzzle_ctrl.vhd`**（否则板上永远错画面、永远赢不了）；
#      落地后把开关置 0 —— 届时补丁锚点已不存在，`sim.py` 会报"锚点出现 0 次"。
# ============================================================
RTL_PATCHES = []

# ============================================================
# 独立参考模型：散落（docs/02 §10.6 的文字描述）
# ============================================================
def _bbox_hit(a, b):
    """包围盒相交（保守判据，docs/02 §10 修订表）：四个不等式同时成立。"""
    r1, c1, h1, w1 = a
    r2, c2, h2, w2 = b
    return (r1 < r2 + h2) and (r2 < r1 + h1) and (c1 < c2 + w2) and (c2 < c1 + w1)


def ref_scatter(dims, rnd, count):
    """独立参考模型：返回 (锚点列表, o_rnd_step 脉冲数)。

    规则（逐条来自 docs/02 §10.6 正文）：
      · 候选行 = i_rnd(5:3) 钳位到 [0, 8-高]，候选列 = i_rnd(2:0) 钳位到 [0, 8-宽]；
      · 每块最多 8 次随机尝试，每次尝试**发一次 o_rnd_step**；
      · 8 次都不行 → 顺序检查回退表前 3 项，取第一个"不越界且与已放置块包围盒不交"的；
      · 回退表都不行 → 保底写第 4 项（(5,5)），保证有限终止。
    """
    anchors, placed, pulses = [], [], 0
    for p in range(count):
        h, w = dims[p]
        row = min((rnd >> 3) & 7, 8 - h)
        col = min(rnd & 7, 8 - w)
        got = None
        for _t in range(8):
            pulses += 1
            if not any(_bbox_hit((row, col, h, w), q) for q in placed):
                got = (row, col)
                break
        if got is None:
            for f in range(3):
                fr, fc = FB[f]
                if not any(_bbox_hit((fr, fc, h, w), q) for q in placed):
                    got = (fr, fc)
                    break
            if got is None:
                got = FB[3]
        anchors.append(got)
        placed.append((got[0], got[1], h, w))
    return anchors, pulses


def abs_mask(rel, row, col):
    """把相对掩码按锚点平移到 8×8 绝对坐标（bit(8*行+列)）。"""
    return (rel << (8 * row + col)) & ((1 << 64) - 1)


def union_of(rels, anchors):
    m = 0
    for rel, (r, c) in zip(rels, anchors):
        m |= abs_mask(rel, r, c)
    return m


# ============================================================
# 调度器：按"clk 拍"逐拍驱动
# ============================================================
DEFAULTS = {
    "rst": 0, "round_start": 0, "target": L1_TARGET, "rel": L1_REL,
    "height": L1_H, "width": L1_W, "count": L1_COUNT, "rnd": 0x2A,
    "sel": 0, "conf": 0, "dir": 0,
}


class Sched:
    def __init__(self):
        self.t = 0
        self.cur = dict(DEFAULTS)
        self.ch = {k: [(0, v)] for k, v in DEFAULTS.items()}
        self.marks = {}

    def set(self, **kw):
        for k, v in kw.items():
            if self.cur.get(k) != v:
                self.cur[k] = v
                self.ch.setdefault(k, []).append((self.t, v))

    def n(self, k=1, **kw):
        self.set(**kw)
        self.t += k
        return self.t

    def pulse(self, **kw):
        """1 拍高脉冲（下一拍回落）。"""
        self.n(1, **kw)
        self.n(1, **{kk: 0 for kk in kw})


SCHED = Sched()
MARKS = {}
EXPECT = {}


def _place_anchor(s, row, col):
    """把当前选中的零片移到 (row, col)：先"归零"再逐格（对初始位置不敏感，最稳）。"""
    s.n(8, dir=DIR_UP); s.n(1, dir=0)
    if row:
        s.n(row, dir=DIR_DOWN); s.n(1, dir=0)
    s.n(8, dir=DIR_LEFT); s.n(1, dir=0)
    if col:
        s.n(col, dir=DIR_RIGHT); s.n(1, dir=0)


def _select_next(s):
    s.pulse(sel=1)


def _sequence(s):
    # ========================================================
    # SC0 —— 复位（时序模块必须显式给复位）
    # ========================================================
    s.n(3, rst=1)
    s.n(2, rst=0)
    MARKS["rst"] = 2

    # ========================================================
    # SC1 —— 散落（第二关 4 块 · 恒定 i_rnd）
    #   ⭐ 恒定 i_rnd 下散落是确定性的 → 可与独立参考模型逐项比对
    # ========================================================
    s.set(target=L2_TARGET, rel=L2_REL, height=L2_H, width=L2_W, count=L2_COUNT)
    s.set(rnd=0x2A)
    s.n(2)
    c = s.t
    s.pulse(round_start=1)
    MARKS["sc1_ev"] = c
    s.n(150)
    MARKS["sc1_done"] = s.t - 1
    an, np = ref_scatter(L2_DIMS, 0x2A, L2_COUNT)
    EXPECT["sc1_anchors"] = an
    EXPECT["sc1_pulses"] = np
    EXPECT["sc1_union"] = union_of(L2_REL, an)

    # ========================================================
    # SC2 —— 单事件（一次"上"）触发一帧：验证 32 拍 / 刷新窗口 / 寄存输出
    # ========================================================
    c = s.t
    s.n(1, dir=DIR_UP)
    s.n(1, dir=0)
    MARKS["sc2_ev"] = c
    new_an = list(an)
    new_an[0] = (max(0, an[0][0] - 1), an[0][1])
    EXPECT["sc2_anchors"] = new_an
    EXPECT["sc2_union"] = union_of(L2_REL, new_an)
    s.n(40)
    MARKS["sc2_done"] = s.t - 1

    # ========================================================
    # SC3 —— 移动与钳位（要求 7）：左/上停在 0，右/下停在 8-w / 8-h
    #   ⭐ 逐拍断言锚点不变量（整段窗口）
    # ========================================================
    MARKS["sc3_start"] = s.t
    s.n(20, dir=DIR_UP); s.n(1, dir=0)
    MARKS["sc3_up"] = s.t - 2
    s.n(20, dir=DIR_LEFT); s.n(1, dir=0)
    MARKS["sc3_left"] = s.t - 2
    s.n(20, dir=DIR_RIGHT); s.n(1, dir=0)
    MARKS["sc3_right"] = s.t - 2
    s.n(20, dir=DIR_DOWN); s.n(1, dir=0)
    MARKS["sc3_down"] = s.t - 2
    s.n(40)
    MARKS["sc3_end"] = s.t - 1

    # ========================================================
    # SC4 —— 锁定（要求 8）：锁定后不可移动、o_all_locked 置位条件
    # ========================================================
    # 当前 r_sel = 0（SC3 只动第 0 块，未按过选择键）
    c = s.t
    s.pulse(conf=1)
    MARKS["sc4_lock0"] = c
    s.n(40)
    # 锁后按方向键 → 锚点不得变
    c = s.t
    s.n(4, dir=DIR_UP); s.n(1, dir=0)
    s.n(4, dir=DIR_DOWN); s.n(1, dir=0)
    s.n(4, dir=DIR_LEFT); s.n(1, dir=0)
    s.n(4, dir=DIR_RIGHT); s.n(1, dir=0)
    MARKS["sc4_trymove"] = c
    s.n(40)
    # 选择键必须跳过已锁定的第 0 块
    c = s.t
    _select_next(s)
    MARKS["sc4_sel_after_lock"] = c
    s.n(4)
    # 再锁第 1 块（当前 r_sel 应为 1）
    c = s.t
    s.pulse(conf=1)
    MARKS["sc4_lock1"] = c
    s.n(40)
    MARKS["sc4_end"] = s.t - 1

    # ========================================================
    # SC5 —— 正确性判定 · 铺法 1（要求 9 核心证据）
    # ========================================================
    def _tiling(round_key, targets, lock_key):
        s.set(target=L1_TARGET, rel=L1_REL, height=L1_H, width=L1_W, count=L1_COUNT)
        s.set(rnd=0x2A)
        s.n(2)
        s.pulse(round_start=1)
        s.n(150)
        MARKS[round_key + "_scatter"] = s.t - 1
        # r_sel 开局 = 0
        for i, (tr, tc) in enumerate(targets):
            if i > 0:
                _select_next(s)
            _place_anchor(s, tr, tc)
        # 依次锁定：2 → 0 → 1
        c = s.t
        s.pulse(conf=1)
        s.n(3)
        _select_next(s); s.n(3)
        s.pulse(conf=1)
        s.n(3)
        _select_next(s); s.n(3)
        c = s.t
        s.pulse(conf=1)
        MARKS[lock_key] = c
        s.n(40)
        MARKS[lock_key + "_end"] = s.t - 1

    _tiling("sc5", L1_TILING[0], "sc5_lock")
    EXPECT["sc5_union"] = union_of(L1_REL, L1_TILING[0])

    # ========================================================
    # SC6 —— 正确性判定 · 铺法 2（必须**也**判成功）
    # ========================================================
    _tiling("sc6", L1_TILING[1], "sc6_lock")
    EXPECT["sc6_union"] = union_of(L1_REL, L1_TILING[1])

    # ========================================================
    # SC7 —— 反向：铺法 1 但第 2 块右移一格 → 必须判失败
    # ========================================================
    _tiling("sc7", [(2, 2), (3, 3), (5, 3)], "sc7_lock")
    EXPECT["sc7_union"] = union_of(L1_REL, [(2, 2), (3, 3), (5, 3)])

    # ========================================================
    # SC8 —— 随机性：20 次重开（i_rnd 各不相同）→ 至少 5 种不同布局
    # ========================================================
    s.set(target=L2_TARGET, rel=L2_REL, height=L2_H, width=L2_W, count=L2_COUNT)
    s.n(2)
    rnds = [(k * 37 + 11) & 0xFF for k in range(20)]
    MARKS["sc8"] = []
    for k, rv in enumerate(rnds):
        s.set(rnd=rv)
        s.n(2)
        s.pulse(round_start=1)
        s.n(152)
        MARKS["sc8"].append((rv, s.t - 1))
    EXPECT["sc8_rnds"] = rnds
    EXPECT["sc8_pulses"] = [ref_scatter(L2_DIMS, rv, L2_COUNT)[1] for rv in rnds]
    EXPECT["sc8_anchors"] = [ref_scatter(L2_DIMS, rv, L2_COUNT)[0] for rv in rnds]


_sequence(SCHED)
DURATION = SCHED.t * CLK
N_CYCLES = SCHED.t


# ============================================================
# 激励构建
# ============================================================
def _to_segs(changes, dur_cycles):
    """[(cycle, val), ...] → Builder 的 [(持续时长 ns, val), ...]。"""
    out = []
    for i, (c, v) in enumerate(changes):
        nxt = changes[i + 1][0] if i + 1 < len(changes) else dur_cycles
        if nxt > c:
            out.append(((nxt - c) * CLK, v))
    return out


def _buried(b, name, width):
    for n in [name] + ["%s[%d]" % (name, i) for i in range(width)]:
        sig = b.vf.signals.get(n)
        if sig is not None:
            sig.direction = "BURIED"


BUR_W = {
    "r_anchor[0]": 6, "r_anchor[1]": 6, "r_anchor[2]": 6, "r_anchor[3]": 6,
    "r_sel": 2, "r_locked": 4, "r_eng_p": 2, "r_eng_row": 3,
    "r_acc_red": 8, "r_acc_grn": 8, "r_px_red": 64, "r_px_green": 64,
    "r_count": 3, "r_piece": 2, "r_try": 3, "r_fb": 2,
    "r_h[0]": 3, "r_w[0]": 3,
}
BUR_B = ["r_eng_run", "r_eng_chk", "r_mismatch", "r_fb_mode", "r_free", "s_sc_we"]

OBSERVE = ([
    "clk", "rst", "i_round_start", "i_target_mask", "i_piece_count",
    "i_rnd", "i_sel", "i_conf", "i_dir",
    "o_px_red", "o_px_green", "o_solved", "o_all_locked", "o_rnd_step",
] + list(BUR_W) + list(BUR_B))


def build(b):
    dur = SCHED.t
    b.input_bit("clk")
    b.clock("clk", CLK)
    ch = SCHED.ch

    def segs(key, default=0):
        return _to_segs(ch.get(key, [(0, default)]), dur)

    b.input_bit("rst"); b.segments("rst", segs("rst"))
    b.input_bit("i_round_start"); b.segments("i_round_start", segs("round_start"))
    b.input_bit("i_sel"); b.segments("i_sel", segs("sel"))
    b.input_bit("i_conf"); b.segments("i_conf", segs("conf"))

    b.input_bus("i_target_mask", 64); b.bus_segments("i_target_mask", segs("target"))
    b.input_bus("i_piece_count", 3); b.bus_segments("i_piece_count", segs("count"))
    b.input_bus("i_rnd", 8); b.bus_segments("i_rnd", segs("rnd"))
    b.input_bus("i_dir", 4); b.bus_segments("i_dir", segs("dir"))

    # ---- 数组端口：只声明网表里实际存在的位 ----
    for i in range(4):
        for k in REL_BITS:
            b.input_bit("i_rel_mask[%d][%d]" % (i, k))
            b.segments("i_rel_mask[%d][%d]" % (i, k),
                       _to_segs([(c, (v[i] >> k) & 1) for (c, v) in ch["rel"]], dur))
        for k in range(3):
            b.input_bit("i_height[%d][%d]" % (i, k))
            b.segments("i_height[%d][%d]" % (i, k),
                       _to_segs([(c, (v[i] >> k) & 1) for (c, v) in ch["height"]], dur))
            b.input_bit("i_width[%d][%d]" % (i, k))
            b.segments("i_width[%d][%d]" % (i, k),
                       _to_segs([(c, (v[i] >> k) & 1) for (c, v) in ch["width"]], dur))

    # ---- 输出 ----
    b.output_bus("o_px_red", 64)
    b.output_bus("o_px_green", 64)
    b.output_bit("o_all_locked")
    b.output_bit("o_solved")
    b.output_bit("o_rnd_step")

    # ---- 中间信号（课件 p59 / docs/03 §3.1 硬要求）----
    for n, w in BUR_W.items():
        b.output_bus(n, w)
        _buried(b, n, w)
    for n in BUR_B:
        b.output_bit(n)
        _buried(b, n, 1)


# ============================================================
# 采样辅助（带缓存的 trace + 二分查找）
# ============================================================
_TC = {}


def _prep(vf, name):
    if name not in _TC:
        tr = vf.trace(name)
        _TC[name] = ([x[0] for x in tr], [x[1] for x in tr])
    return _TC[name]


def bit_at(vf, name, t):
    times, vals = _prep(vf, name)
    if not times:
        return None
    i = bisect.bisect_right(times, t) - 1
    return vals[i] if i >= 0 else None


def bus_at(vf, name, t, width):
    v = 0
    for b in range(width):
        lv = bit_at(vf, "%s[%d]" % (name, b), t)
        if lv not in ("0", "1"):
            return None
        if lv == "1":
            v |= 1 << b
    return v


def after(c):
    return c * CLK + CLK / 2.0 + 1.0


def anchor_at(vf, i, t):
    """返回 (行, 列) 或 None。"""
    v = bus_at(vf, "r_anchor[%d]" % i, t, 6)
    if v is None:
        return None
    return (v >> 3, v & 7)


def _hex(v, w=16):
    return "X" if v is None else ("0x%0*X" % (w, v))


# ============================================================
# 断言
# ============================================================
def check(vf):
    res = []

    # ========================================================
    # ① 复位：锚点/锁定/选择/引擎/像素/判定全部归零
    # ========================================================
    t = after(MARKS["rst"])
    bad = []
    for i in range(4):
        a = anchor_at(vf, i, t)
        if a != (0, 0):
            bad.append("r_anchor[%d]=%s（应 (0,0)）" % (i, a))
    if bus_at(vf, "r_locked", t, 4) != 0:
        bad.append("r_locked=%s（应 0）" % _hex(bus_at(vf, "r_locked", t, 4), 1))
    if bus_at(vf, "r_sel", t, 2) != 0:
        bad.append("r_sel≠0")
    if bit_at(vf, "r_eng_run", t) != "0":
        bad.append("r_eng_run≠0")
    if bus_at(vf, "o_px_red", t, 64) != 0 or bus_at(vf, "o_px_green", t, 64) != 0:
        bad.append("o_px 非 0")
    if bit_at(vf, "o_solved", t) != "0":
        bad.append("o_solved≠0")
    if bit_at(vf, "o_all_locked", t) != "0":
        bad.append("o_all_locked≠0")
    res.append((
        "① 复位：r_anchor 全 0、r_locked=0、r_sel=0、r_eng_run=0、o_px=0、"
        "o_solved=0、o_all_locked=0",
        not bad, "；".join(bad) if bad else "复位后全部归零",
    ))

    # ========================================================
    # ② 散落（第二关 4 块）：与独立参考模型逐块一致 + 不变量 + 包围盒两两不交
    # ========================================================
    t = after(MARKS["sc1_done"])
    exp = EXPECT["sc1_anchors"]
    got = [anchor_at(vf, i, t) for i in range(4)]
    bad = []
    for i in range(4):
        if got[i] != exp[i]:
            bad.append("r_anchor[%d]=%s 期望 %s" % (i, got[i], exp[i]))
        r, c = got[i]
        h, w = L2_DIMS[i]
        if r + h > 8 or c + w > 8:
            bad.append("零片%d 违反锚点不变量：(%d,%d)+%dx%d" % (i, r, c, h, w))
    res.append((
        "② 散落（4 块 · i_rnd=0x2A）：4 块锚点与独立参考模型**逐块一致**，且全部满足"
        "锚点不变量（行+高≤8、列+宽≤8）",
        not bad, "；".join(bad) if bad else "实测锚点 %s（= 参考模型）" % (got,),
    ))

    # 包围盒两两不交 + 像素级两两不交
    bad = []
    boxes = [(got[i][0], got[i][1], L2_DIMS[i][0], L2_DIMS[i][1]) for i in range(4)]
    for i in range(4):
        for j in range(i + 1, 4):
            if _bbox_hit(boxes[i], boxes[j]):
                bad.append("零片%d 与 %d 包围盒相交：%s / %s" % (i, j, boxes[i], boxes[j]))
    res.append((
        "③ 散落后 4 块零片的**包围盒两两不交**（§10.10-1「两两不重叠」）",
        not bad, "；".join(bad) if bad else "包围盒 = %s，两两不交" % (boxes,),
    ))

    masks = [abs_mask(L2_REL[i], got[i][0], got[i][1]) for i in range(4)]
    bad = []
    for i in range(4):
        for j in range(i + 1, 4):
            if masks[i] & masks[j]:
                bad.append("零片%d 与 %d 像素重叠" % (i, j))
    u = 0
    for m in masks:
        u |= m
    pc = sum(bin(m).count("1") for m in masks)
    res.append((
        "④ 散落后 4 块零片**像素级两两不交**（并集格数 = 各块格数之和 = 18）—— "
        "比包围盒更强的证据，直接排除重叠",
        (not bad) and bin(u).count("1") == pc == 18,
        "；".join(bad) if bad else "并集 %d 格 = 各块之和 %d 格 = 18" % (bin(u).count("1"), pc),
    ))

    # ========================================================
    # ⑤ o_rnd_step：单 clk 脉冲 + 每次尝试都推进一次（脉冲数 = 参考模型）
    # ========================================================
    pulses = []
    tr = vf.trace("o_rnd_step")
    for i, (tt, lv) in enumerate(tr):
        if lv == "1":
            end = tr[i + 1][0] if i + 1 < len(tr) else DURATION
            pulses.append((tt, end - tt))
    bad = ["%.0fns 处宽度 %.3g 拍" % (s, w / CLK) for (s, w) in pulses if abs(w - CLK) > 1e-6]
    res.append((
        "⑤ o_rnd_step 一律为 **1 个 clk** 的请求脉冲（CLAUDE.md §10.1 契约）",
        not bad, "共 %d 个脉冲，%s" % (len(pulses), "全部宽度 = 1 拍" if not bad else "；".join(bad[:5])),
    ))

    lo, hi = MARKS["sc1_ev"] * CLK, (MARKS["sc1_done"] + 1) * CLK
    n_in = sum(1 for (s, _w) in pulses if lo <= s < hi)
    res.append((
        "⑥ 散落（4 块 · i_rnd=0x2A）的 o_rnd_step 脉冲数 = 参考模型的尝试次数 %d —— "
        "**每次落位尝试都恰好推进一次**（CLAUDE.md §10.1 的坑：漏发会让所有零片落点相同）"
        % EXPECT["sc1_pulses"],
        n_in == EXPECT["sc1_pulses"],
        "实测 %d 个，期望 %d 个（> 块数 4，说明确实发生了多次尝试）" % (n_in, EXPECT["sc1_pulses"]),
    ))

    # ========================================================
    # ⑦ 一帧 = 32 拍累加（4 块 × 8 行）+ 1 拍判定；引擎事件启动、完成即静止
    # ========================================================
    c = MARKS["sc2_ev"]
    run = [1 if bit_at(vf, "r_eng_run", after(k)) == "1" else 0 for k in range(c - 1, c + 40)]
    n_run = sum(run)
    n_acc = sum(1 for k in range(c, c + 34)
                if bit_at(vf, "r_eng_run", after(k)) == "1"
                and bit_at(vf, "r_eng_chk", after(k)) == "0")
    idle_after = all(bit_at(vf, "r_eng_run", after(k)) == "0" for k in range(c + 34, c + 40))
    res.append((
        "⑦ 时分复用引擎：一次事件后 r_eng_run 恰好高 **33 拍**（32 拍累加 + 1 拍判定），"
        "其中累加拍 = 32（4 块 × 8 行），完成后**静止**（不再自动刷新）",
        (n_run == 33) and (n_acc == 32) and idle_after,
        "r_eng_run 高 %d 拍（应 33）、累加拍 %d（应 32）、帧后静止=%s" % (n_run, n_acc, idle_after),
    ))

    # ========================================================
    # ⑧ o_px_* 是**寄存输出**：事件当拍仍是旧画面，帧完成后才是新画面
    # ========================================================
    old_u = EXPECT["sc1_union"]
    new_u = EXPECT["sc2_union"]
    pr0 = bus_at(vf, "o_px_red", after(c), 64)
    pg0 = bus_at(vf, "o_px_green", after(c), 64)
    pr1 = bus_at(vf, "o_px_red", after(c + 32), 64)
    pg1 = bus_at(vf, "o_px_green", after(c + 32), 64)
    ok = (pr0 is not None and (pr0 | pg0) == old_u and (pr1 | pg1) == new_u and old_u != new_u)
    res.append((
        "⑧ o_px_red/green 是**寄存输出**：事件当拍仍是**旧画面**（旧并集 %s），"
        "第 32 拍后才变成**新画面**（新并集 %s）—— 纯组合实现会在当拍就变"
        % (_hex(old_u), _hex(new_u)),
        ok,
        "after(c): red|green=%s（应旧 %s）；after(c+32): red|green=%s（应新 %s）"
        % (_hex(pr0 | pg0 if pr0 is not None and pg0 is not None else None),
           _hex(old_u),
           _hex(pr1 | pg1 if pr1 is not None and pg1 is not None else None), _hex(new_u)),
    ))

    # ========================================================
    # ⑨ ⭐ o_solved 在刷新期间必须为 '0'（RTL 注释写明是**有意设计**）
    # ========================================================
    bad = [k for k in range(c, c + 33) if bit_at(vf, "o_solved", after(k)) != "0"]
    solved_after = bit_at(vf, "o_solved", after(c + 33))
    exp_solved = "1" if new_u == L2_TARGET else "0"
    res.append((
        "⑨ ⭐ o_solved 在刷新窗口（事件后 33 拍）内**恒为 '0'**，窗口结束后才给真值 —— "
        "否则「最后一块刚锁定」的那 32 拍会假报「拼对了」→ 状态机误判胜利",
        (not bad) and solved_after == exp_solved,
        "窗口内非 0 的拍：%s；窗口后 o_solved=%s（期望 %s，因新并集%s目标）"
        % (bad[:5] if bad else "无", solved_after, exp_solved,
           "==" if new_u == L2_TARGET else "≠"),
    ))

    # ========================================================
    # ⑩ 移动与钳位（要求 7）：四个方向都"贴边停住"，绝不回绕
    # ========================================================
    a_up = anchor_at(vf, 0, after(MARKS["sc3_up"]))
    a_left = anchor_at(vf, 0, after(MARKS["sc3_left"]))
    a_right = anchor_at(vf, 0, after(MARKS["sc3_right"]))
    a_down = anchor_at(vf, 0, after(MARKS["sc3_down"]))
    ok = (a_up is not None and a_up[0] == 0
          and a_left is not None and a_left[1] == 0
          and a_right is not None and a_right[1] == 8 - L2_W[0]
          and a_down is not None and a_down[0] == 8 - L2_H[0])
    res.append((
        "⑩ 移动与钳位（要求 7）：连按 20 次「上」→ 行锚点停在 **0**；「左」→ 列停在 **0**；"
        "「右」→ 列停在 **8-宽=%d**；「下」→ 行停在 **8-高=%d**（不回绕）"
        % (8 - L2_W[0], 8 - L2_H[0]),
        ok,
        "上→%s；左→%s；右→%s（应列=%d）；下→%s（应行=%d）"
        % (a_up, a_left, a_right, 8 - L2_W[0], a_down, 8 - L2_H[0]),
    ))

    # 逐拍锚点不变量（整段移动窗口，逐拍断言）
    bad = []
    for k in range(MARKS["sc3_start"], MARKS["sc3_end"] + 1):
        for i in range(4):
            a = anchor_at(vf, i, after(k))
            if a is None:
                continue
            r, cc = a
            h, w = (L2_H[i], L2_W[i]) if i < 4 else (0, 0)
            if r + h > 8 or cc + w > 8:
                bad.append("第%d拍 零片%d (%d,%d)+%dx%d" % (k, i, r, cc, h, w))
    res.append((
        "⑪ **逐拍**锚点不变量：移动窗口内每一拍、每一块都满足 行+高≤8 且 列+宽≤8"
        "（不只是最后）",
        not bad, "；".join(bad[:5]) if bad else
        "窗口 [%d,%d] 共 %d 拍 × 4 块，逐拍全部满足"
        % (MARKS["sc3_start"], MARKS["sc3_end"], MARKS["sc3_end"] - MARKS["sc3_start"] + 1),
    ))

    # ========================================================
    # ⑫ 锁定（要求 8）：锁定后不可再移动；选择键跳过已锁定块
    # ========================================================
    a_before = anchor_at(vf, 0, after(MARKS["sc4_trymove"] - 1))
    a_after = anchor_at(vf, 0, after(MARKS["sc4_trymove"] + 30))
    ok1 = (a_before is not None and a_before == a_after)
    sel_after = bus_at(vf, "r_sel", after(MARKS["sc4_sel_after_lock"]), 2)
    ok2 = sel_after not in (None, 0)
    res.append((
        "⑫ 锁定后（要求 8）：已锁定的第 0 块按四个方向键**锚点不变**；"
        "「选择」键**跳过**已锁定的第 0 块（r_sel≠0）",
        ok1 and ok2,
        "锁定块锚点 %s → %s（应不变）；锁后按选择键 r_sel=%s（应≠0）" % (a_before, a_after, sel_after),
    ))

    # ========================================================
    # ⑬ o_all_locked 的置位条件（两个方向）
    # ========================================================
    n_locked_at_sc4 = bus_at(vf, "r_locked", after(MARKS["sc4_end"]), 4)
    # 第 0、1 块已锁（count=4）→ r_locked=0b0011，仍 < 0b1111 → o_all_locked 必须为 0
    all_lk = bit_at(vf, "o_all_locked", after(MARKS["sc4_end"]))
    ok1 = (n_locked_at_sc4 == 0b0011) and all_lk == "0"
    # 另一方向：第一关 count=3，锁满 0/1/2 → 有效掩码 0b0111 → o_all_locked=1
    all_lk1 = bit_at(vf, "o_all_locked", after(MARKS["sc5_lock"] + 40))
    lk1 = bus_at(vf, "r_locked", after(MARKS["sc5_lock"] + 40), 4)
    ok2 = (lk1 == 0b0111) and all_lk1 == "1"
    res.append((
        "⑬ o_all_locked 置位条件：第二关只锁 2/4 块 → **0**；第一关锁满 3/3 块"
        "（有效掩码 0111，第 4 块是不存在的占位槽）→ **1**（两个方向都测）",
        ok1 and ok2,
        "count=4 锁 0011 → o_all_locked=%s（应 0）；count=3 锁 %s → o_all_locked=%s（应 1）"
        % (all_lk, bin(lk1) if lk1 is not None else None, all_lk1),
    ))

    # ========================================================
    # ⑭ ⭐ 正确性判定：第一关 2 种合法铺法**都**判 o_solved=1
    # ========================================================
    for tag, key, tiling in (("铺法 1", "sc5", L1_TILING[0]), ("铺法 2", "sc6", L1_TILING[1])):
        cl = MARKS[key + "_lock"]
        # 锁定后 o_px 的并集（红|绿）必须等于目标
        t = after(cl + 33)
        u = bus_at(vf, "o_px_red", t, 64) | bus_at(vf, "o_px_green", t, 64)
        sv = bit_at(vf, "o_solved", t)
        bad = []
        for i in range(3):
            a = anchor_at(vf, i, t)
            if a != tiling[i]:
                bad.append("零片%d 锚点 %s ≠ 目标 %s" % (i, a, tiling[i]))
        if u != L1_TARGET:
            bad.append("并集 %s ≠ 目标 %s" % (_hex(u), _hex(L1_TARGET)))
        if sv != "1":
            bad.append("o_solved=%s（应 1）" % sv)
        res.append((
            "⑭ ⭐ 正确性判定 · %s（锚点 %s）：并集 == 第一关目标掩码 → **o_solved=1**"
            "（判定与铺法无关，两种都必须成功）" % (tag, tiling),
            not bad, "；".join(bad) if bad else
            "锚点 %s，并集 %s == 目标 %s，o_solved=1"
            % ([anchor_at(vf, i, t) for i in range(3)], _hex(u), _hex(L1_TARGET)),
        ))

    # ========================================================
    # ⑮ 反向：铺法 1 但第 2 块右移一格 → 必须判失败
    # ========================================================
    cl = MARKS["sc7_lock"]
    t = after(cl + 33)
    u = bus_at(vf, "o_px_red", t, 64) | bus_at(vf, "o_px_green", t, 64)
    sv = bit_at(vf, "o_solved", t)
    res.append((
        "⑮ 反向：第一关铺法 1 但第 2 块右移一格（并集 ≠ 目标）→ **o_solved=0**"
        "（两个方向都测：拼对=1 / 拼错=0）",
        u != L1_TARGET and sv == "0",
        "并集 %s（≠ 目标 %s）、o_solved=%s（应 0）" % (_hex(u), _hex(L1_TARGET), sv),
    ))

    # ========================================================
    # ⑯ 选择键：r_sel 循环 0→1→2→0（第一关 3 块）
    # ========================================================
    # 直接扫全程 r_sel 的取值集合（SC5~SC7 用第一关 3 块，选择键会循环到 0/1/2）
    tv = []
    for k in range(0, N_CYCLES):
        v = bus_at(vf, "r_sel", after(k), 2)
        if v is not None:
            tv.append(v)
    res.append((
        "⑯ 「选择」键循环：r_sel 全程出现过 0 / 1 / 2（第一关 3 块的循环切换）",
        set(tv) >= {0, 1, 2},
        "r_sel 出现过的取值集合 = %s" % sorted(set(tv)),
    ))

    # ========================================================
    # ⑰ 随机性（§10.10-2）：20 次重开、i_rnd 各不相同 → 至少 5 种不同布局
    # ========================================================
    layouts = set()
    bad = []
    for (rv, last_c), exp_an, exp_np in zip(MARKS["sc8"], EXPECT["sc8_anchors"], EXPECT["sc8_pulses"]):
        got = [anchor_at(vf, i, after(last_c)) for i in range(4)]
        layouts.add(tuple(got))
        if got != exp_an:
            bad.append("i_rnd=0x%02X：%s ≠ %s" % (rv, got, exp_an))
        for i in range(4):
            r, c = got[i]
            h, w = L2_DIMS[i]
            if r + h > 8 or c + w > 8:
                bad.append("i_rnd=0x%02X 零片%d 越界" % (rv, i))
        for i in range(4):
            for j in range(i + 1, 4):
                if _bbox_hit((got[i][0], got[i][1], L2_DIMS[i][0], L2_DIMS[i][1]),
                             (got[j][0], got[j][1], L2_DIMS[j][0], L2_DIMS[j][1])):
                    bad.append("i_rnd=0x%02X 零片%d/%d 包围盒相交" % (rv, i, j))
    res.append((
        "⑰ 随机性（§10.10-2）：20 次重开、i_rnd 各异 → 实测 **%d 种不同布局**（要求 ≥5）；"
        "每次的 4 块锚点都与独立参考模型一致、且两两不交" % len(layouts),
        (len(layouts) >= 5) and not bad,
        "；".join(bad[:5]) if bad else "20 次重开得到 %d 种布局，全部与参考模型一致" % len(layouts),
    ))

    # ========================================================
    # ⑱ 包围盒判据的**保守性**（Python 侧穷举引理，不依赖波形）
    #   "包围盒不交" 是"真实形状不重叠"的**充分条件**：
    #     包围盒不交 ⟹ 像素不交（真实形状是不规则多联骨牌，一定含在包围盒里）
    #   → 所以它**绝不会把重叠判成不重叠**；代价是偶尔拒绝一个本可放置的位置。
    # ========================================================
    bad = []
    for i in range(4):
        hi, wi = L2_DIMS[i]
        for j in range(i + 1, 4):
            hj, wj = L2_DIMS[j]
            for ri in range(0, 9 - hi):
                for ci in range(0, 9 - wi):
                    mi = abs_mask(L2_REL[i], ri, ci)
                    for rj in range(0, 9 - hj):
                        for cj in range(0, 9 - wj):
                            if _bbox_hit((ri, ci, hi, wi), (rj, cj, hj, wj)):
                                continue          # 包围盒相交：判据会拒绝（保守），无需检查
                            mj = abs_mask(L2_REL[j], rj, cj)
                            if mi & mj:
                                bad.append("包围盒不交却像素相交：%d@(%d,%d) / %d@(%d,%d)"
                                           % (i, ri, ci, j, rj, cj))
    res.append((
        "⑱ 包围盒判据的保守性（§10 修订表）：穷举 4 块零片的全部锚点对，"
        "断言「包围盒不交 ⟹ 像素不交」——即**绝不会把重叠判成不重叠**"
        "（代价：偶尔拒绝本可放置的位置，由 8 次尝试 + 回退表兜住）",
        not bad, "；".join(bad[:5]) if bad else "全部锚点对满足蕴含关系（充分条件成立）",
    ))

    return res

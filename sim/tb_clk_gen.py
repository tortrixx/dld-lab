# -*- coding: utf-8 -*-
"""tb_clk_gen.py —— clk_gen 的功能仿真激励与断言

【本模块要回答什么】
    `clk_gen` 是 S1「时钟与节拍」的唯一实体：5 级串行级联分频 + 上电复位 + 按键复位。
    它是**全项目唯一产生复位的地方**（其余 10 个实体都只收 `o_rst`），
    也是**唯一与板上时钟档位绑定**的模块。本 tb 钉三件事：

      ① 5 档节拍的分频比 —— 特别是"第 2~5 级由**上一级的 tick 使能**、不是由 clk 使能"
         这条串行级联的设计要点（docs/02 §3.3 / §3.4）；
      ② 三源复位 `o_rst = btn_rst or por_rst or (not sys_en)` 的时序与"或"关系；
      ③ **两个方向都测**（复位有效/无效、使能开/关、长按/短按）——
         只测一边等于没测（`docs/03` §4.9 的教训）。

【CLK_HZ 缩放】docs/03 §1.2
    `CLK_HZ := 16000`（8000 的 2 倍），tb 的 clk 周期 = 1/16000 s = **62500 ns**。
    ⚠️ 不能取 8000：那时 `CNT_8K = 0`，第 1 级退化成 1:1，串行级联不可区分。
    ⚠️ 但 `6250:1` 那一档是**唯一与板上时钟档位绑定**的分频比，缩放仿真**永远覆盖不到**
       → 另跑一次"全速短跑"（`CLK_HZ = 50_000_000`、clk 20ns、约 1.25 万拍），
         断言两个 `o_tick_8k` 脉冲之间**恰隔 6250 拍**。

【三个场景】用环境变量 `CLK_GEN_SCENARIO` 选（默认 `scaled`）
    scaled     CLK_HZ=16000       —— 覆盖 docs/02 §3.6 的 1~8、10、11
    fullspeed  CLK_HZ=50_000_000  —— 覆盖 6250:1 分频比（板上档位 7 的那一档）
    btnheld    CLK_HZ=16000、i_btn_rst 全程 = 1 —— 覆盖 §3.6-9

【怎么跑】（`sim.py` 一次只跑一个场景；场景由环境变量选）
    python scripts/sim.py run clk_gen --round 1                              # scaled（默认）
    CLK_GEN_SCENARIO=fullspeed python scripts/sim.py run clk_gen --round 2   # 全速短跑
    CLK_GEN_SCENARIO=btnheld   python scripts/sim.py run clk_gen --round 3   # §3.6-9

【中间信号】（课件 p59 / docs/03 §3.1）—— 波形里必须有中间信号
    综合后网表里**内部寄存器可以加进 .vwf**，但类型必须写 `BURIED`；
    写成 OUTPUT 会被报 `Wrong node type ... Design node is of type Buried`。
    ⚠️ `r_div_8k` 在 scaled/btnheld 场景会被综合器**优化掉**（`CNT_8K = 1` 时它与
       `r_tick_8k` 冗余）→ 这两个场景的清单里不含它；只有 fullspeed 才有。
    ⚠️ 本网表的寄存器**上电初值实测为 0**（不是 X）—— `clk_gen` 没有复位输入口，
       若初值是 X 则整个模块不可仿；实测 o_rst/r_por_cnt/r_btn_* 都从 0 起，
       故本 tb 不需要（也无法）显式给复位。
"""

import os

SCENARIO = os.environ.get("CLK_GEN_SCENARIO", "scaled").strip().lower()

# ============================================================
# 场景参数
# ============================================================
# ---- scaled：CLK_HZ = 16000，clk = 62500 ns ----
TICK_8K  = 125_000.0            # 8kHz  → 125 us
TICK_1K  = 1_000_000.0          # 1kHz  → 1 ms
TICK_100 = 10_000_000.0         # 100Hz → 10 ms
TICK_2HZ = 500_000_000.0        # 2Hz   → 500 ms
TICK_1HZ = 1_000_000_000.0      # 1Hz   → 1 s

# ---- 按键时间线（scaled 场景）----
T_PRESS     = 1_050_000_000.0   # 长按开始（应触发复位）
T_RELEASE   = 1_100_000_000.0   # 长按结束（应快速释放）
T_SHORT_ON  = 1_150_000_000.0   # 短按开始（10ms，应被消抖滤掉）
T_SHORT_OFF = 1_160_000_000.0   # 短按结束
T_SYS_OFF   = 1_200_000_000.0   # SW7 拉低（应组合立即复位）

if SCENARIO == "fullspeed":
    CLK_PERIOD = 20.0           # 50MHz
    DURATION = 250_000.0        # 12500 拍 —— 恰好够看到 2 个 tick_8k 脉冲
    GRID_PERIOD = 10.0
    RTL_PATCHES = []            # 不缩放，CLK_HZ 保持 50_000_000
elif SCENARIO == "btnheld":
    CLK_PERIOD = 62_500.0
    DURATION = 30_000_000.0     # 30ms
    GRID_PERIOD = 31_250.0
    RTL_PATCHES = [("puzzle_pkg.vhd", "50_000_000", "16000")]
else:                           # scaled（默认）
    SCENARIO = "scaled"
    CLK_PERIOD = 62_500.0
    DURATION = 1_250_000_000.0  # 1.25 s（含 1s 计数窗 + 按键测试）
    GRID_PERIOD = 31_250.0
    RTL_PATCHES = [("puzzle_pkg.vhd", "50_000_000", "16000")]

# ============================================================
# 端口 / 中间信号
# ============================================================
PORTS_OUT = ["o_rst", "o_tick_8k", "o_tick_1k", "o_tick_100", "o_tick_2hz", "o_tick_1hz"]

# 中间信号：名字 -> 位宽（1 = 单比特）
BURIED = {
    "r_por_cnt": 4, "r_por_rst": 1,
    "r_btn_s0": 1, "r_btn_s1": 1, "r_btn_cnt": 5, "r_btn_rst": 1,
    "r_div_1k": 3, "r_div_100": 4, "r_div_1hz": 7, "r_div_2hz": 6,
}
if SCENARIO == "fullspeed":
    BURIED["r_div_8k"] = 13     # 只有全速场景它才不会被优化掉

OBSERVE = ["clk", "sys_en", "i_btn_rst"] + PORTS_OUT + list(BURIED.keys())


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


def build(b):
    b.input_bit("clk")
    b.input_bit("sys_en")
    b.input_bit("i_btn_rst")
    for n in PORTS_OUT:
        b.output_bit(n)
    for n, w in BURIED.items():
        _decl(b, n, w)
        _buried(b, n, w)

    b.clock("clk", CLK_PERIOD)

    if SCENARIO == "btnheld":
        # i_btn_rst 全程 = 1（§3.6-9）
        b.segments("sys_en", [(DURATION, 1)])
        b.segments("i_btn_rst", [(DURATION, 1)])
    elif SCENARIO == "fullspeed":
        b.segments("sys_en", [(DURATION, 1)])
        b.segments("i_btn_rst", [(DURATION, 0)])
    else:
        b.segments("sys_en", [(T_SYS_OFF, 1), (DURATION - T_SYS_OFF, 0)])
        b.segments("i_btn_rst", [
            (T_PRESS, 0),
            (T_RELEASE - T_PRESS, 1),        # 长按 50ms（≥20ms，应触发）
            (T_SHORT_ON - T_RELEASE, 0),
            (T_SHORT_OFF - T_SHORT_ON, 1),   # 短按 10ms（<20ms，应被滤掉）
            (DURATION - T_SHORT_OFF, 0),
        ])


# ============================================================
# 辅助
# ============================================================
def _lv(vf, name, t):
    return vf.value_at(name, t)


def _rises(vf, name):
    """上升沿时刻列表（0→1）。"""
    return [t for (t, lv) in vf.trace(name) if lv == "1"]


def _count_rise(vf, name, t0, t1):
    """[t0, t1) 内的上升沿个数。"""
    return len([t for t in _rises(vf, name) if t0 <= t < t1])


def _fall_after(vf, name, t0):
    """t0 之后第一个 1→0 跳变时刻。"""
    for (t, lv) in vf.trace(name):
        if t > t0 and lv == "0":
            return t
    return None


def _fmt(t):
    return "X" if t is None else "%.0f ns (%.4f ms)" % (t, t / 1e6)


def _spacing(vf, name):
    """相邻两个上升沿的间隔（取前两个；无则返回 None）。"""
    rs = _rises(vf, name)
    if len(rs) < 2:
        return None
    return "%.0f ns" % (rs[1] - rs[0])


# ============================================================
# 断言
# ============================================================
def _check_scaled(vf):
    res = []

    # ---- 中间信号确实有波形（课件 p59 / docs/03 §3.1 第 5 条）----
    no_wave = [n for n in BURIED if not vf.trace(n) and not any(
        vf.trace("%s[%d]" % (n, i)) for i in range(BURIED[n]))]
    res.append((
        "① 中间信号全部有波形（%d 个：消抖计数器 / 上电计数器 / 各级分频计数器）" % len(BURIED),
        not no_wave,
        "缺失：%s" % no_wave if no_wave else "、".join(BURIED.keys()),
    ))

    # ---- §3.6-1：sys_en=1 时，前 ~10ms o_rst='1'，之后恒 '0' ----
    t_fall = _fall_after(vf, "o_rst", 0.0)
    ok = (_lv(vf, "o_rst", 5e6) == "1" and _lv(vf, "o_rst", 12e6) == "0"
          and _lv(vf, "o_rst", 500e6) == "0" and _lv(vf, "o_rst", 1000e6) == "0"
          and t_fall is not None and 8.0e6 <= t_fall <= 10.6e6)
    res.append((
        "② §3.6-1 上电复位：sys_en=1 时前 ~10ms o_rst='1'，之后恒 '0'",
        ok,
        "o_rst 5ms=%s / 12ms=%s / 500ms=%s / 1000ms=%s；释放时刻 = %s"
        % (_lv(vf, "o_rst", 5e6), _lv(vf, "o_rst", 12e6),
           _lv(vf, "o_rst", 500e6), _lv(vf, "o_rst", 1000e6), _fmt(t_fall)),
    ))

    T0 = 12e6                   # 观察窗起点：POR 已释放、按键尚未动
    # ---- §3.6-4：1ms 内 o_tick_8k 恰好 8 个 ----
    n8 = _count_rise(vf, "o_tick_8k", T0, T0 + TICK_1K)
    res.append((
        "③ §3.6-4 o_tick_8k：1ms 内恰好 8 个（8kHz）",
        n8 == 8,
        "[12ms,13ms) 内实测 %d 个；相邻间隔 = %s（应 %.0f ns）"
        % (n8, _spacing(vf, "o_tick_8k"), TICK_8K),
    ))

    # ---- §3.6-2：1ms 内 o_tick_1k 恰好 1 个 ----
    n1k = _count_rise(vf, "o_tick_1k", T0, T0 + TICK_1K)
    res.append((
        "④ §3.6-2 o_tick_1k：1ms 内恰好 1 个（1kHz）",
        n1k == 1,
        "[12ms,13ms) 内实测 %d 个；相邻间隔 = %s（应 %.0f ns）"
        % (n1k, _spacing(vf, "o_tick_1k"), TICK_1K),
    ))

    # ---- §3.6-10：10ms 内 o_tick_100 恰好 1 个 ----
    n100 = _count_rise(vf, "o_tick_100", T0, T0 + TICK_100)
    res.append((
        "⑤ §3.6-10 o_tick_100：10ms 内恰好 1 个（100Hz）",
        n100 == 1,
        "[12ms,22ms) 内实测 %d 个；相邻间隔 = %s（应 %.0f ns）"
        % (n100, _spacing(vf, "o_tick_100"), TICK_100),
    ))

    # ---- §3.6-3：1s 内 o_tick_1hz 恰好 1 个 ----
    n1hz = _count_rise(vf, "o_tick_1hz", T0, T0 + TICK_1HZ)
    res.append((
        "⑥ §3.6-3 o_tick_1hz：1s 内恰好 1 个（1Hz）",
        n1hz == 1,
        "[12ms,1012ms) 内实测 %d 个；上升沿时刻 = %s"
        % (n1hz, [_fmt(t) for t in _rises(vf, "o_tick_1hz")]),
    ))

    # ---- §3.6-11：1s 内 o_tick_2hz 恰好 2 个 ----
    n2hz = _count_rise(vf, "o_tick_2hz", T0, T0 + TICK_1HZ)
    res.append((
        "⑦ §3.6-11 o_tick_2hz：1s 内恰好 2 个（2Hz）",
        n2hz == 2,
        "[12ms,1012ms) 内实测 %d 个；相邻间隔 = %s（应 %.0f ns）"
        % (n2hz, _spacing(vf, "o_tick_2hz"), TICK_2HZ),
    ))

    # ---- §3.6-6：长按 20ms → o_rst 断言 ----
    t_btn_rise = None
    for (t, lv) in vf.trace("o_rst"):
        if t > T_PRESS and lv == "1":
            t_btn_rise = t
            break
    ok = (_lv(vf, "o_rst", T_PRESS + 18e6) == "0"       # 未满 20ms：还不该断言
          and _lv(vf, "o_rst", T_PRESS + 22e6) == "1"   # 满 20ms：已断言
          and t_btn_rise is not None)
    res.append((
        "⑧ §3.6-6 按键消抖：长按满 20ms 才断言 o_rst（18ms 时仍为 0）",
        ok,
        "按下 %s 后 o_rst 置位于 %s（Δ = %.2f ms）"
        % (_fmt(T_PRESS), _fmt(t_btn_rise),
           (t_btn_rise - T_PRESS) / 1e6 if t_btn_rise else -1),
    ))

    # ---- §3.6-7：松开 → 第 3 个 clk 上升沿释放 ----
    edges = _rises(vf, "clk")
    e0 = next((e for e in edges if e > T_RELEASE), None)
    t_rel = _fall_after(vf, "o_rst", T_RELEASE)
    n_edges = len([e for e in edges if T_RELEASE < e <= t_rel]) if t_rel else -1
    ok = (e0 is not None and t_rel is not None
          and _lv(vf, "o_rst", e0 + 0.5 * CLK_PERIOD) == "1"
          and _lv(vf, "o_rst", e0 + 1.5 * CLK_PERIOD) == "1"
          and _lv(vf, "o_rst", e0 + 2.5 * CLK_PERIOD) == "0"
          and n_edges == 3)
    res.append((
        "⑨ §3.6-7 松开按键：o_rst 在第 3 个 clk 上升沿释放（不再等 20ms）",
        ok,
        "松开 %s；第 1 个沿 %s；释放于 %s（跨 %d 个 clk 上升沿，应 3）"
        % (_fmt(T_RELEASE), _fmt(e0), _fmt(t_rel), n_edges),
    ))

    # ---- §3.6-8：短按 10ms → 被消抖滤掉，o_rst 全程 0 ----
    samples = [T_SHORT_ON + 1e6, T_SHORT_ON + 5e6, T_SHORT_ON + 9e6,
               T_SHORT_OFF + 1e6, T_SHORT_OFF + 10e6]
    bad = [t for t in samples if _lv(vf, "o_rst", t) != "0"]
    res.append((
        "⑩ §3.6-8 短按仅 10ms（< 20ms 消抖窗）→ o_rst 全程为 '0'（真的滤掉了）",
        not bad,
        "采样点 o_rst 实测 = %s" % [_lv(vf, "o_rst", t) for t in samples],
    ))

    # ---- §3.6-5：sys_en 拉低 → o_rst 组合立即为 1 ----
    ok = (_lv(vf, "o_rst", T_SYS_OFF - 1e6) == "0"
          and _lv(vf, "o_rst", T_SYS_OFF + 1e3) == "1"
          and _lv(vf, "o_rst", T_SYS_OFF + 10e6) == "1")
    res.append((
        "⑪ §3.6-5 sys_en 拉低 → o_rst 组合立即 = '1'（三源里唯一不进触发器的项）",
        ok,
        "sys_en 拉低于 %s；o_rst 前 %s / 后 %s / +10ms %s"
        % (_fmt(T_SYS_OFF), _lv(vf, "o_rst", T_SYS_OFF - 1e6),
           _lv(vf, "o_rst", T_SYS_OFF + 1e3), _lv(vf, "o_rst", T_SYS_OFF + 10e6)),
    ))

    return res


def _check_fullspeed(vf):
    res = []
    rs = _rises(vf, "o_tick_8k")
    edges = _rises(vf, "clk")

    def _edge_idx(t):
        """t 在 clk 上升沿序列中的索引（容差匹配）。"""
        for i, e in enumerate(edges):
            if abs(e - t) < 1e-6:
                return i
        return None

    # ① 第一个脉冲落在第 6250 个 clk 上升沿上（0 基索引 6249）
    #    —— 这条把"绝对分频比"钉死，与②的"相邻间隔"互相独立，二者合起来
    #       等价于"连续 3 个脉冲等间隔"，但只需 2 个脉冲就能测（1.25 万拍预算内）
    idx0 = _edge_idx(rs[0]) if rs else None
    res.append((
        "① 全速（CLK_HZ=50MHz, clk 20ns）：第一个 o_tick_8k 脉冲落在第 6250 个 clk 上升沿",
        idx0 == 6249,
        "第一个脉冲 = %s；在 clk 上升沿序列中的索引 = %s（应 6249 = 6250-1）"
        % (_fmt(rs[0]) if rs else "无", idx0),
    ))

    # ② 两个 o_tick_8k 脉冲之间恰隔 6250 拍（唯一与板上档位绑定的分频比）
    n_between = -1
    delta = -1
    if len(rs) >= 2:
        delta = rs[1] - rs[0]
        n_between = len([e for e in edges if rs[0] < e <= rs[1]])
    res.append((
        "② 相邻两个 o_tick_8k 脉冲之间恰隔 6250 拍（6250:1，板上档位 7 的那一档）",
        len(rs) >= 2 and n_between == 6250 and abs(delta - 6250 * CLK_PERIOD) < 1e-6,
        "脉冲 %s / %s；跨 %d 个 clk 上升沿（应 6250）；Δ = %.0f ns（应 %.0f）"
        % (_fmt(rs[0]) if rs else "无", _fmt(rs[1]) if len(rs) > 1 else "无",
           n_between, delta, 6250 * CLK_PERIOD),
    ))

    # 13 位分频计数器在全速场景真实存在，且数到 CNT_8K = 6249
    top = None
    if "r_div_8k" in vf.signals:
        t = 0.0
        vals = []
        while t <= vf.duration:
            v = vf.bus_value_at("r_div_8k", t)
            if v is not None:
                vals.append(v)
            t += CLK_PERIOD
        top = max(vals) if vals else None
    res.append((
        "③ 全速场景下 r_div_8k（13 位）真实存在，计数值达到 CNT_8K = 6249",
        top == 6249,
        "r_div_8k 观测到的最大值 = %s（应 6249）" % top,
    ))
    return res


def _check_btnheld(vf):
    res = []
    # §3.6-9：i_btn_rst 全程 = 1
    #   ① 上电复位期间 o_rst=1；
    #   ② r_por_cnt 照常计到顶（= T_POR_MS-1 = 9）—— 证明上电计数器不被 o_rst 停住；
    #   ③ 消抖满 20ms 后 o_rst 保持 '1'（按键按住 → 一直复位）；
    #   ④ 反向：POR 释放后、消抖未满之前 o_rst 必须为 0（证明是"消抖"在起作用）。
    t_por_fall = _fall_after(vf, "o_rst", 0.0)
    vals = []
    t = 0.0
    while t <= vf.duration:
        v = vf.bus_value_at("r_por_cnt", t)
        if v is not None:
            vals.append(v)
        t += CLK_PERIOD
    por_top = max(vals) if vals else None

    t_btn_rise = None
    for (t2, lv) in vf.trace("o_rst"):
        if t2 > 1e6 and lv == "1":
            t_btn_rise = t2
            break

    res.append((
        "① §3.6-9 上电复位期间（前 ~10ms）o_rst='1'",
        _lv(vf, "o_rst", 5e6) == "1" and t_por_fall is not None,
        "o_rst(5ms)=%s；POR 释放于 %s" % (_lv(vf, "o_rst", 5e6), _fmt(t_por_fall)),
    ))
    res.append((
        "② §3.6-9 r_por_cnt 照常计数到顶（9）—— 上电计数器不被 o_rst 停住",
        por_top == 9,
        "r_por_cnt 观测到的最大值 = %s（应 9 = T_POR_MS-1）" % por_top,
    ))
    res.append((
        "③ §3.6-9 按键按住：消抖满 20ms 后 o_rst 保持 '1'（一直复位）",
        t_btn_rise is not None and _lv(vf, "o_rst", DURATION - 1e6) == "1",
        "o_rst 重新置位于 %s；末态 o_rst=%s"
        % (_fmt(t_btn_rise), _lv(vf, "o_rst", DURATION - 1e6)),
    ))
    res.append((
        "④ §3.6-9 反向：POR 释放后、按键未满 20ms 消抖窗前 o_rst = '0'",
        t_por_fall is not None and t_btn_rise is not None
        and _lv(vf, "o_rst", (t_por_fall + t_btn_rise) / 2) == "0",
        "POR 释放 %s → 消抖认定 %s 之间 o_rst=%s"
        % (_fmt(t_por_fall), _fmt(t_btn_rise),
           _lv(vf, "o_rst", (t_por_fall + t_btn_rise) / 2)
           if (t_por_fall and t_btn_rise) else "X"),
    ))
    return res


def check(vf):
    if SCENARIO == "fullspeed":
        return _check_fullspeed(vf)
    if SCENARIO == "btnheld":
        return _check_btnheld(vf)
    return _check_scaled(vf)

# -*- coding: utf-8 -*-
"""tb_rng_lfsr.py —— rng_lfsr 的功能仿真激励与断言

【本模块的特殊性（与其它模块都不同）】
    ① **不接任何节拍**（CLAUDE.md §10.1 硬约束）：它由 `i_step` 脉冲**请求推进**，
       接的是**原始 `clk`**。所以本 tb **不需要改 `CLK_HZ`**，直接驱动 `clk` 与 `i_step`。
    ② **它是时序模块**：综合后网表寄存器初值是 **X 不是 0** → **必须显式给复位**。
    ③ 它只有**一个** 8 位状态寄存器 `r_lfsr`，`o_rnd` 是它的组合拷贝 —— 这正是
       docs/03 §3.1 要求的"中间信号"（状态寄存器本身）。

【本 tb 的核心断言（逐条对应 docs/02 §9.6 的 6 个验证点）】
    ⭐ 初值非零：`SEED_DEFAULT = x"01"`，且**绝不能是全 0**（全 0 是 LFSR 的吸收态）。
    ⭐ 状态序列逐拍正确：**独立推演**参考序列（tb 里按抽头 bit7/5/4/3 自己算，
       **不从 RTL 抄**），断言实测序列与它**逐拍相同**。
    ⭐ 周期恰为 255：255 拍后回到初值，且中途**不出现 0**。
    ⭐ `i_step` 语义：`'0'` 时状态**必须不变**（不是每个 clk 都推进）；
       `'1'` 时**恰好推进一次**。**两个方向都测**。
    ⭐ `i_seed_load`：装载后状态 == `i_seed`；**装载路径的 `or x"01"` 保护真的生效**
       （非零但 bit0=0 的种子会被按成 bit0=1；全 0 种子被按成 `x"01"`）；
       且**装载优先于步进**。
    ⭐ 均匀性抽查：255 个状态里每个 bit 为 1 的次数恰为 128（最大长度序列的推论）。

【参考模型：独立推演，不看 RTL】
    Fibonacci 型左移 LFSR，抽头 bit7/5/4/3：
        fb      = bit7 ^ bit5 ^ bit4 ^ bit3
        next(s) = ((s << 1) & 0xFF) | fb          # 左移，反馈进 bit0
    从 `x"01"` 出发迭代：第 255 步回到 `x"01"`，255 个非零状态两两不同，
    每个 bit 恰为 128 个 1。**这些结论是本 tb 独立算出来的**，用于和网表比对。

【时间线】（单位 ns，CLK = 20；采样点 = 每个时钟高电平中点，即沿后 5ns）
    0   ~ 40     rst=1（复位，边沿 10/30 各复位一次）→ 状态 = x"01"
    45           采样 seq[0]（复位初值）
    40  ~ 5140   i_step=1 连续 255 拍 → 采样 seq[1..255]（seq[255] 回到 x"01"）
    5140~ 5200   空闲（i_step=0）→ 连续 3 个时钟沿状态必须**纹丝不动**
    5200~ 5220   装载 i_seed=0xAD（bit0=1）→ 状态 == 0xAD
    5220~ 5240   单拍 i_step=1 → 恰好前进 1 步（== next(0xAD)）
    5240~ 5260   装载 i_seed=0xAC（bit0=0）→ 状态 == 0xAD（or 保护置 bit0）
    5260~ 5280   装载 i_seed=0x00 → 状态 == x"01"（or 保护按回非零）
    5280~ 5300   装载 0x00 **同时** i_step=1 → 装载优先，状态 == x"01"
    5300~ 5400   空闲 → 状态稳定保持 x"01"
"""

CLK = 20.0
DURATION = 5400.0
GRID_PERIOD = 10.0

# ---- 复位与推演常量（与 rtl/puzzle_pkg.vhd 的 SEED_DEFAULT 一致，非抄实现）----
SEED_DEFAULT = 0x01
TAPS = (7, 5, 4, 3)          # 反馈抽头：bit7/5/4/3

# ---- 关键时刻 ----
STEP_EDGE0 = 50.0            # 第一个"rst=0 且 i_step=1"的上升沿
RUN_END = 5140.0             # 255 拍推进结束
T_SEQ0 = 45.0                # 复位后初值采样点
T_HOLD = [5155.0, 5175.0, 5195.0]        # 保持相（i_step=0）采样点
T_L1 = 5215.0                # 装载 0xAD 后
T_S1 = 5235.0                # 单拍步进后
T_L2 = 5255.0                # 装载 0xAC 后
T_L3 = 5275.0                # 装载 0x00 后
T_L4 = 5295.0                # 装载 0x00 + step 后（装载优先）
T_IDLE = [5315.0, 5335.0]    # 收尾空闲采样点

SEED_A = 0xAD                # bit0=1：装载后应原样（== i_seed）
SEED_B = 0xAC                # bit0=0 且非零：or 保护应置 bit0 → 0xAD
SEED_ZERO = 0x00             # 全 0：or 保护应按回 0x01

# ---- 激励分段：(起始, 结束, 电平) ----
RST_SPANS = [(0.0, 40.0, 1), (40.0, DURATION, 0)]
STEP_SPANS = [(0.0, 40.0, 0), (40.0, RUN_END, 1), (RUN_END, 5200.0, 0),
              (5200.0, 5220.0, 0), (5220.0, 5240.0, 1), (5240.0, 5260.0, 0),
              (5260.0, 5280.0, 0), (5280.0, 5300.0, 1), (5300.0, DURATION, 0)]
LOAD_SPANS = [(0.0, 5200.0, 0), (5200.0, 5220.0, 1), (5220.0, 5240.0, 0),
              (5240.0, 5300.0, 1), (5300.0, DURATION, 0)]
SEED_SPANS = [(0.0, 5200.0, 0x00), (5200.0, 5240.0, SEED_A),
              (5240.0, 5260.0, SEED_B), (5260.0, DURATION, SEED_ZERO)]

# ⚠️ docs/03 §3.1 第 5 条：清单里的节点缺一即报错（`sim.py check` 会断言）
#    r_lfsr 是本模块唯一的状态寄存器，也是 o_rnd 的驱动源 —— 它就是"中间信号"。
OBSERVE = ["clk", "rst", "i_step", "i_seed_load", "i_seed", "o_rnd", "r_lfsr"]

# 中间信号 r_lfsr 在综合后网表里是**内部节点**，类型必须写 `BURIED`
# （写成 OUTPUT 会被报 `Wrong node type ... Design node is of type Buried`；
#   见 tb_clk_gen.py 的同一处理）
BURIED = {"r_lfsr": 8}


def _buried(b, name, width):
    """把节点（含其比特子节点）标成 BURIED —— 综合后网表里内部信号就是 Buried。"""
    for n in [name] + ["%s[%d]" % (name, i) for i in range(width)]:
        sig = b.vf.signals.get(n)
        if sig is not None:
            sig.direction = "BURIED"


# ============================================================
# 独立参考模型（不看 RTL，按抽头公式自己算）
# ============================================================
def ref_next(s):
    """Fibonacci 左移 LFSR：next = (s<<1) | (bit7^bit5^bit4^bit3)。"""
    fb = 0
    for b in TAPS:
        fb ^= (s >> b) & 1
    return ((s << 1) & 0xFF) | fb


def ref_seq(seed, n):
    """返回 [seed, next(seed), ...]，共 n+1 个值。"""
    out = [seed]
    s = seed
    for _ in range(n):
        s = ref_next(s)
        out.append(s)
    return out


REF = ref_seq(SEED_DEFAULT, 255)     # REF[0..255]，REF[255] 应回到 SEED_DEFAULT


def sample_time(k):
    """第 k 拍状态的采样时刻：k=0 是复位初值，k>=1 是第 k 次步进之后。"""
    if k == 0:
        return T_SEQ0
    return STEP_EDGE0 + CLK * (k - 1) + 5.0


def _segs(spans):
    return [(b - a, lv) for (a, b, lv) in spans]


def build(b):
    """声明节点 + 驱动激励。"""
    b.input_bit("clk")
    b.input_bit("rst")
    b.input_bit("i_step")
    b.input_bit("i_seed_load")
    b.input_bus("i_seed", 8)
    b.output_bus("o_rnd", 8)
    # 中间信号：状态寄存器 r_lfsr（内部节点 → BURIED）
    for n, w in BURIED.items():
        b.output_bus(n, w)
        _buried(b, n, w)

    b.clock("clk", CLK)
    # ⚠️ 必须显式复位：综合后网表寄存器初值是 X，不是 0
    b.segments("rst", _segs(RST_SPANS))
    b.segments("i_step", _segs(STEP_SPANS))
    b.segments("i_seed_load", _segs(LOAD_SPANS))
    b.bus_segments("i_seed", _segs(SEED_SPANS))


def _hex(v):
    return "X" if v is None else ("0x%02X" % v)


# ============================================================
# 断言
# ============================================================
def check(vf):
    res = []

    # 采样 256 个状态：meas[0] = 复位初值，meas[k] = 第 k 次步进后
    meas = [vf.bus_value_at("o_rnd", sample_time(k)) for k in range(256)]

    # ---- ① 复位初值非零，且 == SEED_DEFAULT ----
    ok = meas[0] == SEED_DEFAULT and meas[0] != 0
    res.append((
        "① 复位后 o_rnd == SEED_DEFAULT(x\"01\") 且 ≠ 0（初值非零，未落在吸收态）",
        ok,
        "复位后 o_rnd = %s（期望 0x01，且不得为 0x00）" % _hex(meas[0]),
    ))

    # ---- ② 独立推演序列 vs 实测，逐拍相同 ----
    mism = [(k, meas[k], REF[k]) for k in range(256) if meas[k] != REF[k]]
    detail = ("逐拍比对 256 个状态：全部一致（0..255）"
              if not mism else
              "不一致 %d 处，前 5 处：" % len(mism) +
              "；".join("第%d拍 实测%s 期望%s" % (k, _hex(m), _hex(r)) for (k, m, r) in mism[:5]))
    res.append((
        "② 实测状态序列与【独立推演】的参考序列（抽头 bit7/5/4/3）逐拍完全一致",
        not mism, detail,
    ))

    # ---- ③ 周期恰为 255 ----
    back = [k for k in range(1, 255) if meas[k] == SEED_DEFAULT]
    ok = meas[255] == SEED_DEFAULT and not back
    res.append((
        "③ 周期恰为 255：第 255 拍回到初值，且第 1~254 拍均未回到初值",
        ok,
        "第 255 拍 = %s（期望 0x01）；1~254 拍中回到初值的次数 = %d"
        % (_hex(meas[255]), len(back)),
    ))

    # ---- ④ 全程不出现 0（未落入吸收态）----
    zeros = [k for k in range(256) if meas[k] == 0]
    res.append((
        "④ 全程 o_rnd 永不为 0（255 个状态遍历全部非零状态，不落入吸收态）",
        not zeros,
        "出现 0 的拍号：%s" % (zeros if zeros else "无"),
    ))

    # ---- ⑤ 255 个状态两两不同（最大长度序列）----
    vals = meas[0:255]
    ok = len(set(vals)) == 255
    res.append((
        "⑤ 一个周期内 255 个状态两两不同（最大长度序列的定义）",
        ok,
        "不同状态数 = %d / 255" % len(set(vals)),
    ))

    # ---- ⑥ 均匀性：每 bit 为 1 的次数恰为 128 ----
    counts = [sum((v >> b) & 1 for v in vals if v is not None) for b in range(8)]
    ok = all(c == 128 for c in counts)
    res.append((
        "⑥ 均匀性抽查：255 个状态中每个 bit 为 1 的次数恰为 128（非退化序列）",
        ok,
        "各 bit 的 1 计数（bit7→bit0）= %s（期望全 128）" % counts,
    ))

    # ---- ⑦ i_step='0' → 状态保持不变（连续 3 个时钟沿）----
    hold = [vf.bus_value_at("o_rnd", t) for t in T_HOLD]
    ok = len(set(hold)) == 1 and hold[0] == meas[255] and hold[0] != 0
    res.append((
        "⑦ i_step='0' 时状态保持不变（连续 3 个时钟沿纹丝不动，证明不是每拍都推进）",
        ok,
        "3 个时钟沿采样 = %s（应全等于第 255 拍 %s）"
        % ([_hex(x) for x in hold], _hex(meas[255])),
    ))

    # ---- ⑧ i_step='1' 恰好推进一次（单脉冲前进 1 步）----
    v = vf.bus_value_at("o_rnd", T_S1)
    want = ref_next(SEED_A)
    ok = v == want and v != SEED_A
    res.append((
        "⑧ 单拍 i_step='1' 恰好推进一次（从装载值 0xAD 前进 1 步，不多不少）",
        ok,
        "实测 %s，期望 next(0xAD) = %s（若没推进会是 0xAD）" % (_hex(v), _hex(want)),
    ))

    # ---- ⑨ i_seed_load 装载：状态 == i_seed ----
    v = vf.bus_value_at("o_rnd", T_L1)
    res.append((
        "⑨ i_seed_load=1 装载 0xAD → 状态 == i_seed（bit0=1 的种子原样装入）",
        v == SEED_A,
        "实测 %s，期望 %s" % (_hex(v), _hex(SEED_A)),
    ))

    # ---- ⑩ 装载的 or x"01" 保护：非零但 bit0=0 的种子被置 bit0 ----
    v = vf.bus_value_at("o_rnd", T_L2)
    want = SEED_B | 0x01
    res.append((
        "⑩ 装载 0xAC（非零但 bit0=0）→ 状态 == 0xAD（or x\"01\" 保护真的生效）",
        v == want,
        "实测 %s，期望 0xAC | 0x01 = %s" % (_hex(v), _hex(want)),
    ))

    # ---- ⑪ 装载 x"00" → 状态非零 ----
    v = vf.bus_value_at("o_rnd", T_L3)
    res.append((
        "⑪ 装载 x\"00\"（全 0，吸收态种子）→ 状态被按回 x\"01\"（非零，第二道防线）",
        v == SEED_DEFAULT and v != 0,
        "实测 %s，期望 0x01" % _hex(v),
    ))

    # ---- ⑫ 装载优先于步进（同时为 1 时以装载为准）----
    v = vf.bus_value_at("o_rnd", T_L4)
    step_wins = ref_next(SEED_DEFAULT)
    res.append((
        "⑫ i_seed_load 优先于 i_step：两者同时为 1 时按装载走（结果非零）",
        v == SEED_DEFAULT,
        "实测 %s；若步进获胜会是 next(0x01) = %s（装载优先故为 0x01）"
        % (_hex(v), _hex(step_wins)),
    ))

    # ---- ⑬ 收尾空闲：状态稳定保持（不因时钟自走）----
    idle = [vf.bus_value_at("o_rnd", t) for t in T_IDLE]
    ok = len(set(idle)) == 1 and idle[0] == SEED_DEFAULT
    res.append((
        "⑬ 收尾空闲（i_step=0）→ 状态稳定保持 x\"01\"（时钟自走不改变状态）",
        ok,
        "采样 = %s" % [_hex(x) for x in idle],
    ))

    # ---- ⑭ 中间信号自洽：状态寄存器 r_lfsr 与组合输出 o_rnd 逐拍相同 ----
    #    （课件 p59 / docs/03 §3.1：波形里必须有中间信号，且它要能解释输出）
    rl = [vf.bus_value_at("r_lfsr", sample_time(k)) for k in range(256)]
    bad = [(k, rl[k], meas[k]) for k in range(256) if rl[k] != meas[k]]
    res.append((
        "⑭ 中间信号 r_lfsr（状态寄存器）与 o_rnd 逐拍相同（o_rnd 是它的组合拷贝）",
        not bad,
        "不一致 %d 处" % len(bad) if bad else "256 拍全部一致（r_lfsr == o_rnd）",
    ))

    return res

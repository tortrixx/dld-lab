# -*- coding: utf-8 -*-
"""tb_game_fsm.py —— game_fsm（主状态机 + BCD 倒计时 + 键号译码 + 音效选择）功能仿真

【本模块要钉死什么】
    `game_fsm` 是"时间调度器"：6 个状态、全部迁移边、倒计时、键号译码、音效事件。
    本 tb 逐条覆盖 `docs/02` §12.9 的**全部 19 行验证点**（编号 1~19），并额外钉三件事：

      ⭐ **ERR-0035 的全局边**：`game_fsm` 里那条"任意状态按开始 → 直接进 S_PREVIEW"
        写在 `case r_state` **之前**（`rtl/game_fsm.vhd:246`）—— 任何状态都拦不住。
        上板时一个**幻影「开始」**（键盘极性错）就把系统从自检态踢出（ERR-0035 / ERR-0039）。
        本 tb 对 **6 个状态各按一次「开始」**，断言**全部**直接进 `S_PREVIEW`，
        并特别断言 `S_SELF_TEST` 在数满 4 个 `tick_2hz` **之前**也会被踢出。

      ⭐ **脉冲宽度契约**（`CLAUDE.md` §10.1 / §12.8 要点 6/9）：
        `o_sel_out` / `o_conf_out` / `o_round_start` / `o_sound_trig` / `o_dir_out`
        一律**恰好 1 个 clk**（20ns）。逐条量宽度。

      ⭐ **`o_blink` 是 2Hz 方波**（§12.9-19）：由 `i_tick_100 ÷ 25` 再翻转得到，
        **不是**把 `i_tick_2hz` 的单周期使能直通（那样只有 1Hz）。跑 50 个 `tick_100`
        数翻转次数，必须恰好 2 次（半周期 25 拍）。

【独立来源，不自证】
    期望值来自 `docs/02` §12 的**状态输出表 / 迁移边表 / 译码表 / 音效触发表**
    （状态编码另见 `rtl/puzzle_pkg.vhd` §2.7、`docs/01` §8.2），**不从 RTL 反抄**。
    键号→动作的期望来自 §12.2 的译码表；BCD 递减的期望用 Python 独立算一遍。

【时间模型】（clk 20ns；三个节拍端口直接驱动，不改 `CLK_HZ`）
    所有输入按**逐 clk 周期**给出。第 c 个周期的 clk 上升沿在 t = 20c + 10 ns。
    `i_tick_1hz` / `i_tick_2hz` / `i_tick_100` 都做成"高 1 个 clk"的单周期使能
    （与板上一致，见 `rtl/clk_gen.vhd`）。
    ⚠️ 时序模块必须显式给复位：综合后网表寄存器初值是 X 不是 0。

【中间信号】（课件 p59 / `docs/03` §3.1）—— 波形里必须有中间信号
    收录 `r_state`（状态寄存器）、`r_preview_cnt` / `r_cnt_tens` / `r_cnt_ones`
    （倒计时）、`r_self_cnt`（自检计时）、`r_blink` / `r_blink_div`（2Hz 方波）、
    `r_repeat_cnt`（连发）、`r_pattern_sel` / `r_seed`（图案随机）等。
    综合后网表里内部信号必须声明为 **BURIED**（写成 OUTPUT 会报
    `Wrong node type ... Design node is of type Buried`，见 `tb_buzzer_ctrl.py`）。
"""

CLK = 20.0
GRID_PERIOD = 10.0

# ============================================================
# 参考常量（独立来源：docs/02 §12 / rtl/puzzle_pkg.vhd §2.7 / docs/01 §8.2）
# ============================================================
S_SELF, S_IDLE, S_PREV, S_PLAY, S_WIN, S_FAIL = 0, 1, 2, 3, 4, 5
STATE_NAME = {0: "S_SELF_TEST", 1: "S_IDLE", 2: "S_PREVIEW",
              3: "S_PLAYING", 4: "S_WIN", 5: "S_FAIL"}

# 键号 → 动作（docs/02 §12.2 译码表）
KEY_UP, KEY_START, KEY_LEFT, KEY_DOWN, KEY_RIGHT, KEY_SEL, KEY_CONF = 2, 4, 5, 6, 7, 8, 12
DIR_CODE = {KEY_UP: 0x8, KEY_DOWN: 0x4, KEY_LEFT: 0x2, KEY_RIGHT: 0x1}
BLANK_KEYS = [1, 3, 9, 10, 11, 13, 14, 15, 16]

# 音效号（docs/02 §12.7A）
SND_KEY, SND_MOVE, SND_LOCK, SND_PREV, SND_LAST5, SND_WIN, SND_FAIL = 1, 2, 3, 4, 5, 6, 7

# 端口 / 中间信号位宽
INPUT_W = {"rst": 1, "i_tick_1hz": 1, "i_tick_2hz": 1, "i_tick_100": 1,
           "i_key_press": 1, "i_all_locked": 1, "i_solved": 1, "i_key_code": 5}
OUT_W = {"o_state": 3, "o_blink": 1, "o_level": 1, "o_preview_cnt": 3,
         "o_game_cnt_bcd": 8, "o_pattern_sel": 3, "o_round_start": 1,
         "o_sel_out": 1, "o_conf_out": 1, "o_dir_out": 4, "o_sound_sel": 3,
         "o_sound_trig": 1, "o_seed_load": 1, "o_seed": 8}
BUR_W = {"r_state": 3, "r_level": 1, "r_preview_cnt": 3, "r_cnt_tens": 4,
         "r_cnt_ones": 4, "r_self_cnt": 2, "r_blink": 1, "r_blink_div": 5,
         "r_repeat_cnt": 3, "r_dir_out": 4, "r_pattern_sel": 3, "r_seed": 8,
         "r_pv_load": 1, "r_cnt_load": 1, "r_seed_load": 1}
ALL_W = {}
ALL_W.update(INPUT_W)
ALL_W.update(OUT_W)
ALL_W.update(BUR_W)

OBSERVE = ["clk"] + list(INPUT_W) + list(OUT_W) + list(BUR_W)

# 输入信号（不含 clk，clk 由 Builder.clock 生成）
INPUTS = list(INPUT_W)


# ============================================================
# 调度器：按"clk 周期"逐拍驱动
# ============================================================
class Sched:
    def __init__(self):
        self.t = 0
        self.cur = {n: 0 for n in INPUTS}
        self.segs = {n: [] for n in INPUTS}

    def hold(self, n=1, **kw):
        for k, v in kw.items():
            self.cur[k] = v
        for name in INPUTS:
            self.segs[name].append((n, self.cur[name]))
        self.t += n
        return self.t

    def one(self, **kw):
        return self.hold(1, **kw)

    # 单周期节拍脉冲（高 1 拍 + 低 1 拍 = 2 拍）
    def p1hz(self):
        self.one(i_tick_1hz=1); self.one(i_tick_1hz=0)
    def p2hz(self):
        self.one(i_tick_2hz=1); self.one(i_tick_2hz=0)
    def p100(self):
        self.one(i_tick_100=1); self.one(i_tick_100=0)


def after(c):
    """第 c 个周期 clk 上升沿之后（读寄存器输出）。"""
    return c * CLK + CLK / 2.0 + 1.0


def during(c):
    """第 c 个周期内、clk 上升沿之前（读 Mealy 组合输出）。"""
    return c * CLK + CLK / 2.0 - 5.0


# ============================================================
# 探针 / 标记
# ============================================================
PROBES = []     # (group, label, signal, time_ns, expected_int)
MARKS = {}


def P(group, label, sig, t, exp):
    PROBES.append((group, label, sig, t, exp))


# ============================================================
# 激励序列（模块导入时就跑一遍，check() 用同一份 PROBES / MARKS）
# ============================================================
def _press(s, key):
    """按下一个键：i_key_press 高 1 拍，返回该拍周期号。"""
    c = s.t
    s.one(i_key_code=key, i_key_press=1)
    s.one(i_key_code=key, i_key_press=0)
    s.one(i_key_code=0)
    return c


def _reset(s, pad=0):
    """复位（高 3 拍）后释放；pad = 释放后额外空拍（用于改变随机种子奇偶）。"""
    s.hold(3, rst=1)
    c = s.t
    s.one(rst=0)
    if pad:
        s.hold(pad)
    return c


def _to_idle(s, pad=0):
    """复位 → 4 个 tick_2hz → S_IDLE，返回第 4 个 tick 的周期号。"""
    _reset(s, pad)
    cc = None
    for _ in range(4):
        cc = s.t
        s.p2hz()
    return cc


def _to_preview(s, pad=0):
    """S_IDLE → 按开始 → S_PREVIEW，返回按下的周期号。"""
    _to_idle(s, pad)
    return _press(s, KEY_START)


def _to_playing(s, pad=0):
    """S_PREVIEW（5 秒倒计时）→ S_PLAYING，返回 (按下周期号, [5 个 tick 周期号])。"""
    c = _to_preview(s, pad)
    ticks = []
    for _ in range(5):
        cc = s.t
        s.p1hz()
        ticks.append(cc)
    return c, ticks


def _sequence(s):
    # ========================================================
    # SC1 —— §12.9-1（复位→自检 2 秒→待机） + §12.9-19（2Hz 方波）
    # ========================================================
    s.hold(3, rst=1)
    c_rst = s.t
    s.one(rst=0)
    P("§12.9-1 复位→自检→待机", "复位后 o_state=S_SELF_TEST(000)", "o_state", after(c_rst), S_SELF)
    P("§12.9-1 复位→自检→待机", "复位后 o_level=0", "o_level", after(c_rst), 0)
    P("§12.9-1 复位→自检→待机", "复位后 r_state=S_SELF_TEST", "r_state", after(c_rst), S_SELF)

    # --- §12.9-19：自检态跑 50 个 tick_100，o_blink 恰好翻转 2 次（半周期 25 拍）---
    b0 = s.t
    for _ in range(50):
        s.p100()
    b1 = s.t
    MARKS["blink"] = (b0, b1)
    P("§12.9-19 o_blink 2Hz 方波", "50 个 tick_100 期间状态仍为 S_SELF_TEST（无 tick_2hz）",
      "o_state", after(b1 - 1), S_SELF)

    # --- §12.9-1：自检数 4 个 tick_2hz 才迁 S_IDLE ---
    for k in range(1, 5):
        cc = s.t
        s.p2hz()
        if k < 4:
            P("§12.9-1 复位→自检→待机", "自检第 %d 个 tick_2hz 后仍 S_SELF_TEST" % k,
              "o_state", after(cc), S_SELF)
            P("§12.9-1 复位→自检→待机", "自检第 %d 拍 r_self_cnt=%d" % (k, k),
              "r_self_cnt", after(cc), k)
        else:
            P("§12.9-1 复位→自检→待机", "自检第 4 个 tick_2hz 后 → S_IDLE",
              "o_state", after(cc), S_IDLE)
            P("§12.9-1 复位→自检→待机", "自检第 4 拍 r_self_cnt 清零",
              "r_self_cnt", after(cc), 0)
    MARKS["selftest_ticks"] = 4

    # ========================================================
    # SC0 —— ERR-0035：全局边「任意状态按开始 → S_PREVIEW」之 S_SELF_TEST
    # ========================================================
    _reset(s)
    c_press = _press(s, KEY_START)
    G = "ERR-0035 幻影开始键踢出自检态"
    P(G, "S_SELF_TEST（未满 4 拍）按开始 → 立即 S_PREVIEW", "o_state", after(c_press), S_PREV)
    P(G, "→ o_level=0", "o_level", after(c_press), 0)
    P(G, "→ o_round_start 脉冲", "o_round_start", after(c_press), 1)
    P(G, "→ r_self_cnt 被清零", "r_self_cnt", after(c_press), 0)
    P("§12.9-12 任意状态重开全局边", "S_SELF_TEST 按开始 → S_PREVIEW",
      "o_state", after(c_press), S_PREV)

    # ========================================================
    # SC2 —— §12.9-2 / -17：S_IDLE 按开始 → S_PREVIEW
    # ========================================================
    _to_idle(s)
    s.hold(1)
    c_press = _press(s, KEY_START)
    G2 = "§12.9-2 待机按开始→预览"
    P(G2, "S_IDLE 按开始 → S_PREVIEW", "o_state", after(c_press), S_PREV)
    P(G2, "→ o_level=0", "o_level", after(c_press), 0)
    P(G2, "→ o_preview_cnt 装载为 5", "o_preview_cnt", after(c_press + 1), 5)
    P(G2, "→ o_seed_load 出脉冲", "o_seed_load", after(c_press), 1)
    P(G2, "→ o_seed_load 只有 1 拍", "o_seed_load", after(c_press + 1), 0)
    P("§12.9-17 o_round_start 单周期且时刻", "进入 S_PREVIEW 那一拍 o_round_start=1",
      "o_round_start", after(c_press), 1)
    P("§12.9-17 o_round_start 单周期且时刻", "o_round_start 只有 1 拍",
      "o_round_start", after(c_press + 1), 0)
    P("§12.9-14 音效触发单周期脉冲", "按键音效 o_sound_sel=001", "o_sound_sel", after(c_press), SND_KEY)
    P("§12.9-14 音效触发单周期脉冲", "按键 o_sound_trig=1", "o_sound_trig", after(c_press), 1)
    P("§12.9-14 音效触发单周期脉冲", "o_sound_trig 只有 1 拍", "o_sound_trig", after(c_press + 1), 0)
    MARKS["seed_sample"] = after(c_press)

    # ========================================================
    # SC3 —— §12.9-12：S_PREVIEW 按开始 → 仍 S_PREVIEW（重开一局）
    # ========================================================
    s.hold(1)
    c_press = _press(s, KEY_START)
    G12 = "§12.9-12 任意状态重开全局边"
    P(G12, "S_PREVIEW 按开始 → 仍 S_PREVIEW", "o_state", after(c_press), S_PREV)
    P(G12, "S_PREVIEW 重开 → o_level=0", "o_level", after(c_press), 0)
    P(G12, "S_PREVIEW 重开 → o_round_start 脉冲", "o_round_start", after(c_press), 1)
    P(G12, "S_PREVIEW 重开 → o_preview_cnt 回到 5", "o_preview_cnt", after(c_press + 1), 5)

    # ========================================================
    # SC4 —— §12.9-3：预览恰好 5 秒（5→4→3→2→1，减到 1 同拍迁 S_PLAYING）
    # ========================================================
    G3 = "§12.9-3 预览 5 秒倒计时"
    pv_ticks = []
    for k in range(5):
        cc = s.t
        s.p1hz()
        pv_ticks.append(cc)
        exp_cnt = 5 - (k + 1)
        exp_st = S_PLAY if k == 4 else S_PREV
        P(G3, "第 %d 个 tick_1hz 后 o_preview_cnt=%d" % (k + 1, exp_cnt),
          "o_preview_cnt", after(cc), exp_cnt)
        P(G3, "第 %d 个 tick_1hz 后 o_state=%s" % (k + 1, STATE_NAME[exp_st]),
          "o_state", after(cc), exp_st)
        P("§12.9-14 音效触发单周期脉冲", "预览倒计时每秒 o_sound_sel=100",
          "o_sound_sel", after(cc), SND_PREV)
        P("§12.9-14 音效触发单周期脉冲", "预览倒计时 o_sound_trig 脉冲",
          "o_sound_trig", after(cc), 1)
    MARKS["preview_ticks"] = pv_ticks
    P("§12.9-4/5 BCD 倒计时与不回绕", "进入 S_PLAYING 后装载 0x30",
      "o_game_cnt_bcd", after(pv_ticks[-1] + 1), 0x30)

    # ========================================================
    # SC5 —— §12.9-12：S_PLAYING 按开始 → S_PREVIEW
    # ========================================================
    s.hold(1)
    c_press = _press(s, KEY_START)
    P(G12, "S_PLAYING 按开始 → S_PREVIEW", "o_state", after(c_press), S_PREV)
    P(G12, "S_PLAYING 重开 → o_level=0", "o_level", after(c_press), 0)
    P(G12, "S_PLAYING 重开 → o_round_start 脉冲", "o_round_start", after(c_press), 1)

    # ========================================================
    # SC6 —— §12.9-6：第一关拼对 → level=1 + 回 S_PREVIEW
    # ========================================================
    _, _ = _to_playing(s)
    cc = s.t
    s.one(i_all_locked=1, i_solved=1)
    s.one(i_all_locked=0, i_solved=0)
    G6 = "§12.9-6 第一关拼对→第二关预览"
    P(G6, "全锁且拼对（level=0）→ o_level=1", "o_level", after(cc), 1)
    P(G6, "→ 回 S_PREVIEW（不直接判胜）", "o_state", after(cc), S_PREV)
    P(G6, "→ o_round_start 脉冲（第二关重新散落）", "o_round_start", after(cc), 1)
    P(G6, "→ o_round_start 只有 1 拍", "o_round_start", after(cc + 1), 0)
    P(G6, "→ o_preview_cnt 重新装载 5", "o_preview_cnt", after(cc + 1), 5)

    # ========================================================
    # SC7 —— §12.9-7 / -18：第二关拼对 → S_WIN
    # ========================================================
    G7 = "§12.9-7 第二关拼对→胜利"
    G18 = "§12.9-18 第二关 40 秒"
    cc2 = None
    for _ in range(5):
        cc2 = s.t
        s.p1hz()
    P(G18, "第二关进入 S_PLAYING 装载 0x40", "o_game_cnt_bcd", after(cc2 + 1), 0x40)
    cc3 = s.t
    s.one(i_all_locked=1, i_solved=1)
    s.one(i_all_locked=0, i_solved=0)
    P(G7, "第二关全锁且拼对 → S_WIN", "o_state", after(cc3), S_WIN)
    P(G7, "→ o_pattern_sel=011（胜利图案）", "o_pattern_sel", after(cc3 + 1), 3)
    P("§12.9-14 音效触发单周期脉冲", "胜利音效 o_sound_sel=110", "o_sound_sel", after(cc3), SND_WIN)
    P("§12.9-14 音效触发单周期脉冲", "胜利 o_sound_trig 脉冲", "o_sound_trig", after(cc3), 1)
    P("§12.9-14 音效触发单周期脉冲", "胜利 o_sound_trig 只有 1 拍", "o_sound_trig", after(cc3 + 1), 0)

    # --- §12.9-12：S_WIN 按开始 → S_PREVIEW ---
    s.hold(1)
    c_press = _press(s, KEY_START)
    P(G12, "S_WIN 按开始 → S_PREVIEW", "o_state", after(c_press), S_PREV)
    P(G12, "S_WIN 重开 → o_level=0", "o_level", after(c_press), 0)
    P(G12, "S_WIN 重开 → o_round_start 脉冲", "o_round_start", after(c_press), 1)

    # ========================================================
    # SC8 —— §12.9-8：全锁但没拼对 → 立即 S_FAIL
    # ========================================================
    _to_playing(s)
    cc = s.t
    s.one(i_all_locked=1, i_solved=0)
    s.one(i_all_locked=0, i_solved=0)
    G8 = "§12.9-8 全锁未拼对→失败"
    P(G8, "S_PLAYING 全锁但拼错 → 立即 S_FAIL", "o_state", after(cc), S_FAIL)
    P(G8, "→ o_pattern_sel=100（失败图案）", "o_pattern_sel", after(cc + 1), 4)
    P("§12.9-14 音效触发单周期脉冲", "失败音效 o_sound_sel=111", "o_sound_sel", after(cc), SND_FAIL)
    P("§12.9-14 音效触发单周期脉冲", "失败 o_sound_trig 脉冲", "o_sound_trig", after(cc), 1)

    # --- §12.9-12：S_FAIL 按开始 → S_PREVIEW ---
    s.hold(1)
    c_press = _press(s, KEY_START)
    P(G12, "S_FAIL 按开始 → S_PREVIEW", "o_state", after(c_press), S_PREV)
    P(G12, "S_FAIL 重开 → o_level=0", "o_level", after(c_press), 0)
    P(G12, "S_FAIL 重开 → o_round_start 脉冲", "o_round_start", after(c_press), 1)

    # ========================================================
    # SC9 —— §12.9-4 / -5：第一关倒计时 30 秒 → 0x00 → S_FAIL（不回绕 0x99）
    # ========================================================
    _, seq = _to_playing(s)
    base = seq[-1] + 1
    cnt_cycles = []
    for k in range(30):
        cc = s.t
        s.p1hz()
        cnt_cycles.append(cc)
    MARKS["cnt30"] = (base, cnt_cycles)
    G45 = "§12.9-4/5 BCD 倒计时与不回绕"
    P(G45, "倒计时第 30 拍 → S_FAIL", "o_state", after(cnt_cycles[-1]), S_FAIL)
    P(G45, "倒计时第 30 拍 o_game_cnt_bcd=0x00", "o_game_cnt_bcd", after(cnt_cycles[-1]), 0x00)
    P("§12.9-14 音效触发单周期脉冲", "最后一秒（0x01）音效 o_sound_sel=111",
      "o_sound_sel", after(cnt_cycles[-1]), SND_FAIL)
    # 最后 5 秒的滴答音（0x05..0x02 → sound 5）
    P("§12.9-14 音效触发单周期脉冲", "最后 5 秒（0x05）音效 o_sound_sel=101",
      "o_sound_sel", after(cnt_cycles[-5]), SND_LAST5)
    # FAIL 后继续给 tick，断言 cnt 保持 0x00（不回绕 0x99）
    for _ in range(3):
        cc = s.t
        s.p1hz()
        P(G45, "FAIL 后 cnt 保持 0x00（不回绕 0x99）", "o_game_cnt_bcd", after(cc), 0x00)
        P(G45, "FAIL 后状态保持 S_FAIL", "o_state", after(cc), S_FAIL)

    # ========================================================
    # SC10 —— §12.9-18：第二关倒计时 40 秒 → 0x00 → S_FAIL
    # ========================================================
    _to_playing(s)
    cc = s.t
    s.one(i_all_locked=1, i_solved=1)
    s.one(i_all_locked=0, i_solved=0)
    cc2 = None
    for _ in range(5):
        cc2 = s.t
        s.p1hz()
    P(G18, "第二关进 S_PLAYING 装载 0x40", "o_game_cnt_bcd", after(cc2 + 1), 0x40)
    cc1 = s.t
    s.p1hz()
    P(G18, "第二关第 1 拍后 0x39（证明装的是 40 不是 30）", "o_game_cnt_bcd", after(cc1), 0x39)
    ccN = None
    for _ in range(39):
        ccN = s.t
        s.p1hz()
    P(G18, "第二关 40 拍后 → S_FAIL", "o_state", after(ccN), S_FAIL)
    P(G18, "第二关 40 拍后 cnt=0x00", "o_game_cnt_bcd", after(ccN), 0x00)

    # ========================================================
    # SC11 —— §12.9-11：键号译码 1~16（只有 2/4/5/6/7/8/12 有动作）
    # ========================================================
    _to_playing(s)
    G11 = "§12.9-11 键号译码"
    order = [1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, KEY_START]
    for key in order:
        s.hold(1)
        cc = s.t
        s.one(i_key_code=key, i_key_press=1)
        s.one(i_key_code=key, i_key_press=0)
        s.one(i_key_code=0)
        if key == KEY_START:
            P(G11, "键 4（开始）→ 全局边，状态变 S_PREVIEW", "o_state", after(cc), S_PREV)
        elif key in DIR_CODE:
            P(G11, "键 %d → o_dir_out=0x%X（方向独热）" % (key, DIR_CODE[key]),
              "o_dir_out", after(cc), DIR_CODE[key])
            P(G11, "键 %d → o_sel_out=0" % key, "o_sel_out", during(cc), 0)
            P(G11, "键 %d → o_conf_out=0" % key, "o_conf_out", during(cc), 0)
            P(G11, "键 %d → 状态不变 S_PLAYING" % key, "o_state", after(cc), S_PLAY)
            P(G11, "键 %d → 按键音 o_sound_sel=001" % key, "o_sound_sel", after(cc), SND_KEY)
        elif key == KEY_SEL:
            P(G11, "键 8（选择）→ o_sel_out=1", "o_sel_out", during(cc), 1)
            P(G11, "键 8 → o_dir_out=0", "o_dir_out", after(cc), 0)
            P(G11, "键 8 → o_conf_out=0", "o_conf_out", during(cc), 0)
            P(G11, "键 8 → 状态不变 S_PLAYING", "o_state", after(cc), S_PLAY)
            P(G11, "键 8 → 按键音 o_sound_sel=001", "o_sound_sel", after(cc), SND_KEY)
        elif key == KEY_CONF:
            P(G11, "键 12（确认）→ o_conf_out=1", "o_conf_out", during(cc), 1)
            P(G11, "键 12 → o_dir_out=0", "o_dir_out", after(cc), 0)
            P(G11, "键 12 → o_sel_out=0", "o_sel_out", during(cc), 0)
            P(G11, "键 12 → 状态不变 S_PLAYING", "o_state", after(cc), S_PLAY)
            P("§12.9-14 音效触发单周期脉冲", "键 12 锁定音 o_sound_sel=011",
              "o_sound_sel", after(cc), SND_LOCK)
        else:
            P(G11, "空白键 %d → o_dir_out=0（无动作）" % key, "o_dir_out", after(cc), 0)
            P(G11, "空白键 %d → o_sel_out=0" % key, "o_sel_out", during(cc), 0)
            P(G11, "空白键 %d → o_conf_out=0" % key, "o_conf_out", during(cc), 0)
            P(G11, "空白键 %d → o_sound_trig=0（不产生音效）" % key,
              "o_sound_trig", after(cc), 0)
            P(G11, "空白键 %d → 状态不变 S_PLAYING" % key, "o_state", after(cc), S_PLAY)

    # ========================================================
    # SC12 —— §12.9-10 / -15：方向键连发（首拍 + 500ms 后每 100ms 一次）
    # ========================================================
    _to_playing(s)
    s.hold(2)
    c_press = s.t
    s.one(i_key_code=KEY_LEFT, i_key_press=1)
    tick_c = []
    for _ in range(9):
        s.one(i_key_code=KEY_LEFT, i_key_press=0)
        cc = s.t
        s.one(i_key_code=KEY_LEFT, i_tick_100=1)
        s.one(i_key_code=KEY_LEFT, i_tick_100=0)
        tick_c.append(cc)
    s.one(i_key_code=0)
    MARKS["repeat"] = (c_press, tick_c)
    G10 = "§12.9-10 方向键连发"
    P(G10, "首拍立即响应 o_dir_out=0x2（左）", "o_dir_out", after(c_press), DIR_CODE[KEY_LEFT])
    P(G10, "首拍下一拍归 0", "o_dir_out", after(c_press + 1), 0)
    P(G10, "第 4 个 tick_100 仍未连发（无脉冲）", "o_dir_out", after(tick_c[3]), 0)
    P(G10, "第 5 个 tick_100 首次连发（=500ms，不是 600ms）",
      "o_dir_out", after(tick_c[4]), DIR_CODE[KEY_LEFT])
    P(G10, "此后每 tick_100 一个（第 6 个）", "o_dir_out", after(tick_c[5]), DIR_CODE[KEY_LEFT])
    P(G10, "此后每 tick_100 一个（第 9 个）", "o_dir_out", after(tick_c[8]), DIR_CODE[KEY_LEFT])
    P("§12.9-15 i_key_press 语义", "按住期间 i_key_press=0 但连发照常（第 7 个 tick）",
      "o_dir_out", after(tick_c[6]), DIR_CODE[KEY_LEFT])
    P("§12.9-14 音效触发单周期脉冲", "连发移动音效 o_sound_sel=010（dir 脉冲下一拍）",
      "o_sound_sel", after(tick_c[4] + 1), SND_MOVE)
    P("§12.9-14 音效触发单周期脉冲", "连发移动 o_sound_trig 脉冲（dir 脉冲下一拍）",
      "o_sound_trig", after(tick_c[4] + 1), 1)

    # --- 反向：非方向键按住不产生连发 ---
    s.hold(1)
    c_sel = s.t
    s.one(i_key_code=KEY_SEL, i_key_press=1)
    for _ in range(9):
        s.one(i_key_code=KEY_SEL, i_key_press=0)
        s.one(i_key_code=KEY_SEL, i_tick_100=1)
        s.one(i_key_code=KEY_SEL, i_tick_100=0)
    s.one(i_key_code=0)
    MARKS["nondir"] = (c_sel, s.t)

    # ========================================================
    # SC13 —— §12.9-13：S_IDLE 下按住方向键 → o_dir_out 恒 0
    # ========================================================
    _to_idle(s)
    s.hold(1)
    idle_start = s.t
    s.one(i_key_code=KEY_LEFT, i_key_press=1)
    for _ in range(9):
        s.one(i_key_code=KEY_LEFT, i_key_press=0)
        s.one(i_key_code=KEY_LEFT, i_tick_100=1)
        s.one(i_key_code=KEY_LEFT, i_tick_100=0)
    s.one(i_key_code=0)
    MARKS["idle_dir"] = (idle_start, s.t)
    P("§12.9-13 非拼图态方向键无效", "S_IDLE 按方向键首拍 o_dir_out=0",
      "o_dir_out", after(idle_start), 0)
    P("§12.9-13 非拼图态方向键无效", "S_IDLE 连发期间 o_dir_out=0",
      "o_dir_out", after(idle_start + 5), 0)

    # ========================================================
    # SC14 —— §12.9-9：第二关图案随机（重开 20 次，001/010 都出现）
    # ========================================================
    pat_samples = []
    for i in range(20):
        _to_preview(s, pad=(i % 2))
        for _ in range(5):
            s.p1hz()
        cc = s.t
        s.one(i_all_locked=1, i_solved=1)
        s.one(i_all_locked=0, i_solved=0)
        pat_samples.append(cc + 1)
    MARKS["pat_samples"] = pat_samples

    # ========================================================
    # SC15 —— §12.9-16：第二关通关后立刻重开，新一局第一秒内不得出现 S_FAIL/S_WIN
    # ========================================================
    _to_playing(s)
    cc = s.t
    s.one(i_all_locked=1, i_solved=1)
    s.one(i_all_locked=0, i_solved=0)
    for _ in range(5):
        s.p1hz()
    cc3 = s.t
    s.one(i_all_locked=1, i_solved=1)
    s.one(i_all_locked=0, i_solved=0)
    G16 = "§12.9-16 胜利后立即重开"
    P(G16, "第二关通关 → S_WIN", "o_state", after(cc3), S_WIN)
    s.hold(1)
    c_press = _press(s, KEY_START)
    P(G16, "通关后立刻按开始 → S_PREVIEW", "o_state", after(c_press), S_PREV)
    P(G16, "→ o_level=0", "o_level", after(c_press), 0)
    for k in range(5):
        cc4 = s.t
        s.p1hz()
        exp = S_PLAY if k == 4 else S_PREV
        P(G16, "重开后第 %d 秒仍无 S_FAIL/S_WIN（%s）" % (k + 1, STATE_NAME[exp]),
          "o_state", after(cc4), exp)


SCHED = Sched()
_sequence(SCHED)
DURATION = SCHED.t * CLK


# ============================================================
# 激励构建
# ============================================================
def _buried(b, name, width):
    for n in [name] + ["%s[%d]" % (name, i) for i in range(width)]:
        sig = b.vf.signals.get(n)
        if sig is not None:
            sig.direction = "BURIED"


def build(b):
    b.input_bit("clk")
    for n, w in INPUT_W.items():
        if w > 1:
            b.input_bus(n, w)
        else:
            b.input_bit(n)
    for n, w in OUT_W.items():
        if w > 1:
            b.output_bus(n, w)
        else:
            b.output_bit(n)
    for n, w in BUR_W.items():
        if w > 1:
            b.output_bus(n, w)
        else:
            b.output_bit(n)
        _buried(b, n, w)

    b.clock("clk", CLK)
    for n in INPUTS:
        segs = [(d * CLK, v) for (d, v) in SCHED.segs[n]]
        if INPUT_W[n] > 1:
            b.bus_segments(n, segs)
        else:
            b.segments(n, segs)


# ============================================================
# 采样 / 断言辅助
# ============================================================
def _val(vf, sig, t):
    w = ALL_W[sig]
    if w > 1:
        return vf.bus_value_at(sig, t)
    v = vf.value_at(sig, t)
    return {"0": 0, "1": 1}.get(v)


def _hex(v):
    return "X" if v is None else ("0x%02X" % v)


def _bit_highs(vf, name):
    tr = vf.trace(name)
    out = []
    for i, (t, lv) in enumerate(tr):
        if lv == "1":
            end = tr[i + 1][0] if i + 1 < len(tr) else DURATION
            out.append((t, end))
    return out


def _bus_nonzero(vf, name):
    sig = vf.signals[name]
    times = set()
    for bb in range(sig.width):
        for (t, _lv) in vf.trace("%s[%d]" % (name, bb)):
            times.add(t)
    times = sorted(times)
    out, cur = [], None
    for i, t in enumerate(times):
        nxt = times[i + 1] if i + 1 < len(times) else DURATION
        v = vf.bus_value_at(name, (t + nxt) / 2.0)
        nz = (v is not None and v != 0)
        if nz and cur is None:
            cur = t
        if not nz and cur is not None:
            out.append((cur, t))
            cur = None
    if cur is not None:
        out.append((cur, DURATION))
    return out


def _bcd_sub1(v):
    t = (v >> 4) & 0xF
    o = v & 0xF
    if o == 0:
        return ((t - 1) << 4) | 9 if t > 0 else 0
    return (t << 4) | (o - 1)


# ============================================================
# 断言
# ============================================================
def check(vf):
    res = []

    # ---------- ① 逐条探针（按组聚合）----------
    groups = []
    for (g, _l, _s, _t, _e) in PROBES:
        if g not in groups:
            groups.append(g)
    for g in groups:
        items = [p for p in PROBES if p[0] == g]
        bad = []
        for (_g, label, sig, t, exp) in items:
            got = _val(vf, sig, t)
            if got != exp:
                bad.append("%s：实测 %s，期望 %s（t=%.0fns）"
                           % (label, _hex(got), _hex(exp), t))
        res.append((g, not bad,
                    "%d 项探针全部吻合" % len(items) if not bad
                    else "\n".join(bad[:6])))

    # ---------- ② §12.9-19：o_blink 2Hz 方波（50 个 tick_100 翻转 2 次）----------
    b0, b1 = MARKS["blink"]
    t0, t1 = b0 * CLK, b1 * CLK
    tr = [(t, lv) for (t, lv) in vf.trace("o_blink") if t0 < t <= t1]
    flips = [t for (t, lv) in tr if lv in ("0", "1")]
    n_flip = len(flips)
    # 每个 tick_100 脉冲间隔 2 个 clk → 半周期（tick_100 拍数）= Δclk / 2
    half = (flips[1] - flips[0]) / (2.0 * CLK) if n_flip >= 2 else None
    res.append((
        "§12.9-19 o_blink 是 2Hz 方波（由 tick_100÷25 再翻转，不是 tick_2hz 直通）",
        n_flip == 2 and half is not None and abs(half - 25.0) < 1e-6,
        "50 个 tick_100 内 o_blink 翻转 %d 次（应 2）；半周期 = %s 个 tick_100（应 25）"
        % (n_flip, ("%.3g" % half) if half is not None else "—"),
    ))

    # ---------- ③ §12.9-4/5：BCD 倒计时逐拍递减 + 借位 + 不回绕 ----------
    base, cnt_cycles = MARKS["cnt30"]
    expect = 0x30
    seq_ok, bad_bcd = True, []
    for k, cc in enumerate(cnt_cycles, 1):
        expect = _bcd_sub1(expect)
        got = vf.bus_value_at("o_game_cnt_bcd", after(cc))
        if got != expect:
            seq_ok = False
            bad_bcd.append("第 %d 拍：实测 %s 期望 %s" % (k, _hex(got), _hex(expect)))
    # 0x10 → 0x09 → 0x08 单点
    g10 = vf.bus_value_at("o_game_cnt_bcd", after(cnt_cycles[19]))
    g09 = vf.bus_value_at("o_game_cnt_bcd", after(cnt_cycles[20]))
    g08 = vf.bus_value_at("o_game_cnt_bcd", after(cnt_cycles[21]))
    seen_99 = any(vf.bus_value_at("o_game_cnt_bcd", after(cc)) == 0x99 for cc in cnt_cycles)
    res.append((
        "§12.9-4/5 BCD 倒计时：0x30 逐拍递减到 0x00，0x10→0x09（借位）→0x08，"
        "全程不出现 0x99 回绕",
        seq_ok and (g10, g09, g08) == (0x10, 0x09, 0x08) and not seen_99,
        "30 拍全部吻合=%s；0x10 后=%s、再后=%s、再后=%s（期望 0x10/0x09/0x08）；"
        "出现 0x99=%s%s"
        % (seq_ok, _hex(g10), _hex(g09), _hex(g08), seen_99,
           "" if seq_ok else "\n" + "\n".join(bad_bcd[:6])),
    ))

    # ---------- ④ §12.9-10：方向键连发脉冲个数与首次时刻 ----------
    c_press, tick_c = MARKS["repeat"]
    edge = lambda c: c * CLK + CLK / 2.0        # clk 上升沿时刻 = 波形跳变时刻
    win0, win1 = edge(c_press) - 1.0, edge(tick_c[-1]) + CLK
    pulses = [(s, e) for (s, e) in _bus_nonzero(vf, "o_dir_out") if win0 <= s < win1]
    want_starts = [edge(c_press)] + [edge(t) for t in tick_c[4:]]
    ok_cnt = len(pulses) == len(want_starts)
    ok_time = ok_cnt and all(abs(pulses[i][0] - want_starts[i]) < 1.0
                             for i in range(len(pulses)))
    res.append((
        "§12.9-10 方向键连发：首拍 1 个 + 500ms 起每 100ms 一个（9 个 tick_100 → 共 6 个）",
        ok_cnt and ok_time,
        "实测脉冲 %d 个（应 %d）；时刻 = %s ns；期望 = %s ns"
        % (len(pulses), len(want_starts),
           ["%.0f" % p[0] for p in pulses], ["%.0f" % t for t in want_starts]),
    ))

    # ---------- ⑤ §12.9-10 反向：非方向键按住不连发 ----------
    nd0, nd1 = MARKS["nondir"]
    nd_p = [(s, e) for (s, e) in _bus_nonzero(vf, "o_dir_out")
            if nd0 * CLK <= s < nd1 * CLK]
    res.append((
        "§12.9-10/13 反向：非方向键（选择）按住 9 个 tick_100 也不产生 o_dir_out 脉冲",
        not nd_p,
        "该窗口内 o_dir_out 非零脉冲数 = %d（应 0）" % len(nd_p),
    ))

    # ---------- ⑥ §12.9-13：S_IDLE 方向键全程无效 ----------
    i0, i1 = MARKS["idle_dir"]
    id_p = [(s, e) for (s, e) in _bus_nonzero(vf, "o_dir_out")
            if i0 * CLK <= s < i1 * CLK]
    res.append((
        "§12.9-13 非拼图态（S_IDLE）按住方向键 + 连发窗口 → o_dir_out 全程为 0",
        not id_p,
        "S_IDLE 窗口内 o_dir_out 非零脉冲数 = %d（应 0）" % len(id_p),
    ))

    # ---------- ⑦ §12.9-9：第二关图案 001/010 都出现过 ----------
    pats = sorted(set(vf.bus_value_at("o_pattern_sel", after(c)) for c in MARKS["pat_samples"]))
    res.append((
        "§12.9-9 第二关图案随机：重开 20 次，o_pattern_sel 的 001 与 010 都出现过",
        set(pats) == {0b001, 0b010},
        "20 次重开采到的图案集合 = %s（期望 {0x01, 0x02}）"
        % ("{%s}" % ", ".join(_hex(p) for p in pats)),
    ))

    # ---------- ⑧ 脉冲宽度契约：一律 1 个 clk ----------
    def _widths(name):
        return [((e - s) / CLK, s) for (s, e) in _bit_highs(vf, name)]

    bad_a = []
    for n in ["o_sel_out", "o_conf_out", "o_round_start"]:
        for (w, s) in _widths(n):
            if abs(w - 1.0) > 1e-6:
                bad_a.append("%s 在 %.0fns 处宽度 %.3g 拍" % (n, s, w))
    for bb in range(4):
        for (w, s) in _widths("o_dir_out[%d]" % bb):
            if abs(w - 1.0) > 1e-6:
                bad_a.append("o_dir_out[%d] 在 %.0fns 处宽度 %.3g 拍" % (bb, s, w))
    res.append((
        "脉冲宽度契约（CLAUDE.md §10.1）：o_sel_out/o_conf_out/o_round_start/o_dir_out "
        "一律恰好 1 个 clk",
        not bad_a,
        "全部脉冲宽度均为 1 拍" if not bad_a else "；".join(bad_a[:8]),
    ))

    # ---------- ⑨ §12.8 要点 9：o_sound_trig 一律单周期 ----------
    bad_b = []
    for (w, s) in _widths("o_sound_trig"):
        if abs(w - 1.0) > 1e-6:
            s0 = vf.bus_value_at("o_sound_sel", s + 1)
            s1 = vf.bus_value_at("o_sound_sel", s + CLK + 1)
            bad_b.append("%.0fns 处宽度 %.3g 拍（o_sound_sel %s→%s）"
                         % (s, w, _hex(s0), _hex(s1)))
    res.append((
        "§12.8 要点 9 / CLAUDE.md §10.1：o_sound_trig 一律单周期脉冲（1 个 clk）",
        not bad_b,
        "全部 o_sound_trig 脉冲宽度均为 1 拍" if not bad_b
        else "发现 %d 处宽度 ≠ 1 拍：%s" % (len(bad_b), "；".join(bad_b[:8])),
    ))

    # ---------- ⑨ §12.9-2：种子非零 ----------
    seed = vf.bus_value_at("o_seed", MARKS["seed_sample"])
    res.append((
        "§12.9-2 按开始采样种子：o_seed 非零（LFSR 全 0 是吸收态）",
        seed is not None and seed != 0,
        "采样到的 o_seed = %s（应非 0）" % _hex(seed),
    ))

    return res

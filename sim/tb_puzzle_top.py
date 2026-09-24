# -*- coding: utf-8 -*-
"""tb_puzzle_top.py —— puzzle_top 功能仿真激励与断言（整机 13 场景）

【迭代 2：探测内部信号名】
"""

CLK_NS = 62500.0
DURATION = 500_000_000.0
GRID_PERIOD = 100_000.0

RTL_PATCHES = [
    ("rtl/puzzle_pkg.vhd", "50_000_000", "16000"),
]

OBSERVE = ["clk", "sw7", "btn", "kp_row", "kp_col",
           "dot_row", "dot_colr", "dot_colg", "seg", "cat", "buzz"]


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

    # 候选内部信号（不放入 OBSERVE，先探测哪些存在）
    for name in ["s_state", "s_blink", "s_all_locked", "s_solved",
                 "s_key_press", "s_sound_trig",
                 "u_game_fsm|r_state", "u_game_fsm|o_state",
                 "u_game_fsm|r_blink",
                 "u_puzzle_ctrl|o_all_locked", "u_puzzle_ctrl|o_solved"]:
        b.output_bit(name)

    b.clock("clk", CLK_NS)
    b.segments("sw7", [(DURATION, 1)])
    b.segments("btn", [(100_000_000.0, 1), (DURATION - 100_000_000.0, 0)])
    b.bus_segments("kp_row", [(DURATION, 0xF)])


def check(vf):
    # 打印哪些内部信号有波形
    found = []
    for name in ["s_state", "s_blink", "s_all_locked", "s_solved",
                 "s_key_press", "s_sound_trig",
                 "u_game_fsm|r_state", "u_game_fsm|o_state",
                 "u_game_fsm|r_blink",
                 "u_puzzle_ctrl|o_all_locked", "u_puzzle_ctrl|o_solved"]:
        tr = vf.trace(name)
        if tr:
            found.append(name)
    res = [("Found internal signals", True, str(found))]
    return res

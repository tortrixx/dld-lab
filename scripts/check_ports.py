#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_ports.py —— 接口连通性检查：每个输入端口必须有驱动源，每个输出端口必须有接收者

用途
----
把 docs/01-系统设计.md §10.2「输入端口必须有驱动源」这条**人工核对动作脚本化**。
port map 里漏写一根线不会报错，综合器按默认值处理 —— 若漏的是输入，那根线就是悬空的，
模块照常综合、行为却是错的（ERR-0010 / ERR-0011 的教训）。

核对方向必须是「从线到模块」（逐个数每个 i_* 端口的发出方），不能按模块翻 ——
每个模块的端口表单独看都是自洽的，"缺线"在按模块看时没有可比对象。

方法
----
1. 解析 docs/01 §5 的 12 张接口定义表（§5.0 是包，跳过），得到 11 个实体的全部端口；
2. 端口名归一化（去 i_/o_ 前缀）得到"线名"，个别改名的线用 ALIAS_IN 显式登记；
3. 集合相减：
   - 每个输入端口 → 必须能在"全项目输出端口线名集"或"系统/板级输入"里找到驱动源；
   - 每个输出端口 → 必须能在"全项目输入端口线名集"或"板级输出"里找到接收者。

用法
----
    python scripts/check_ports.py            # 正常检查，全部通过退出码 0
    python scripts/check_ports.py --selftest # 负向测试：注入假端口，确认能检出

退出码非 0 表示存在悬空端口（或自检失败），可用于提交前检查。
"""

import io
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DOC = "docs/01-系统设计.md"

# ---------------------------------------------------------------
# 归一化与豁免规则（改接口时同步维护本段 —— 这是全脚本唯一需要手工维护的部分）
# ---------------------------------------------------------------

# 系统级信号：由顶层直接驱动 / 全设计共享，不参与"模块间驱动源"检查
GLOBAL_WIRES = {"clk", "rst", "sys_en"}

# 板级输入（外部器件 → FPGA），是输入端口的合法驱动源
# btn：BTN0 复位键（课件 PDF p45（一）强制"复位必须用按键来实现"）—— 2026-09-18 补入
TOP_DEVICE_INPUTS = {"kp_row", "btn"}

# 板级输出（FPGA → 外部器件），是输出端口的合法去处
TOP_DEVICE_OUTPUTS = {"kp_col", "seg", "cat", "dot_row", "dot_colr", "dot_colg", "buzz"}

# 输入端口 → 实际线名 的别名表：(模块, 去前缀端口名) → 线名
# 登记的是"同一根线、上下游名字不同"的情况（docs/01 §5.7 的"端口名 ↔ 连线名的别名"一节）
ALIAS_IN = {
    ("keypad_scan", "tick"): "tick_1k",        # i_tick 接的是 tick_1k
    ("seg_scan", "tick"): "tick_8k",           # i_tick 接的是 tick_8k（2026-09-18 刷新率修正）
    ("dot_matrix_scan", "tick"): "tick_8k",
    ("pattern_rom", "sel"): "pattern_sel",      # i_sel = 图案选择，不是"选择"键
    ("puzzle_ctrl", "sel"): "sel_out",          # 由 game_fsm.o_sel_out 转发
    ("puzzle_ctrl", "conf"): "conf_out",
    ("puzzle_ctrl", "dir"): "dir_out",
    ("puzzle_ctrl", "piece_count"): "count",    # 来自 piece_rom.o_count
    ("puzzle_ctrl", "target_mask"): "mask",     # 来自 pattern_rom.o_mask
    ("disp_format", "pattern_mask"): "mask",    # 同上，o_mask 的第二去处
    ("rng_lfsr", "step"): "rnd_step",           # 由 puzzle_ctrl.o_rnd_step 驱动
    ("buzzer_ctrl", "trigger"): "sound_trig",   # 由 game_fsm.o_sound_trig 驱动
    ("clk_gen", "btn_rst"): "btn",              # i_btn_rst 接的是顶层板级输入 btn（同 sw7→sys_en）
}

EXPECTED_MODULES = 11   # §5.1 ~ §5.11（§5.0 是包，不是实体）


def strip_prefix(name):
    """i_xxx / o_xxx → xxx"""
    if name.startswith(("i_", "o_")):
        return name[2:]
    return name


def parse_ports(path):
    """
    解析 docs/01 §5 的接口定义表。
    返回 {模块名: {"in": [端口名...], "out": [端口名...]}}，端口名保留 i_/o_ 前缀。
    """
    with io.open(path, encoding="utf-8") as f:
        text = f.read()

    # 只取 §5 与 §6 之间的内容
    m5 = re.search(r"^## 5\.\s", text, re.M)
    m6 = re.search(r"^## 6\.\s", text, re.M)
    if not m5 or not m6:
        raise SystemExit("✗ 未找到 docs/01 的 §5 / §6 边界，文档结构可能已改版")
    body = text[m5.start():m6.start()]

    modules = {}
    current = None
    for line in body.splitlines():
        h = re.match(r"^### 5\.\d+\s+`([a-z0-9_]+)`", line)
        if h:
            name = h.group(1)
            if name == "puzzle_pkg":
                current = None            # 包不是实体，跳过
            else:
                current = name
                modules[current] = {"in": [], "out": []}
            continue
        if current is None or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        port_cell, direction = cells[0], cells[1]
        if direction not in ("in", "out"):
            continue                      # 表头 / 分隔行 / "—" 分节行
        for port in re.findall(r"`([a-z0-9_]+)`", port_cell):
            modules[current][direction].append(port)
    return modules


def check(modules):
    """返回 (缺驱动源的输入列表, 无接收者的输出列表, 每个输入的驱动源对照表)。"""
    produced = {}    # 线名 → 产生它的 "模块.端口" 列表（px_red 等透传线有两个生产者）
    consumed = set() # 被消费的线名
    input_rows = []  # (模块, 输入端口, 解析后的线名, 驱动源描述 or None)

    for mod, dirs in modules.items():
        for port in dirs["out"]:
            produced.setdefault(strip_prefix(port), []).append("%s.%s" % (mod, port))

    for mod, dirs in modules.items():
        for port in dirs["in"]:
            base = strip_prefix(port)
            wire = ALIAS_IN.get((mod, base), base)
            if base in GLOBAL_WIRES:
                src = "（系统级：顶层直连）"
            elif wire in TOP_DEVICE_INPUTS:
                src = "（板级输入：外部器件）"
            elif wire in produced:
                src = " / ".join(produced[wire])
            else:
                src = None
            input_rows.append((mod, port, wire, src))
            if wire not in GLOBAL_WIRES and wire not in TOP_DEVICE_INPUTS:
                consumed.add(wire)

    missing_in = [(m, p, w) for m, p, w, s in input_rows if s is None]

    orphan_out = []
    for mod, dirs in modules.items():
        for port in dirs["out"]:
            wire = strip_prefix(port)
            if wire in GLOBAL_WIRES or wire in TOP_DEVICE_OUTPUTS:
                continue
            if wire not in consumed:
                orphan_out.append((mod, port, wire))

    return missing_in, orphan_out, input_rows


def report(modules, missing_in, orphan_out, input_rows):
    print("=" * 64)
    print("接口连通性检查（docs/01 §5 ↔ 驱动源/接收者）")
    print("=" * 64)
    print("解析到实体 %d 个（期望 %d）：%s" % (
        len(modules), EXPECTED_MODULES, "、".join(sorted(modules))))
    n_in = sum(len(d["in"]) for d in modules.values())
    n_out = sum(len(d["out"]) for d in modules.values())
    print("输入端口 %d 个，输出端口 %d 个" % (n_in, n_out))
    print("-" * 64)

    ok = True
    if len(modules) != EXPECTED_MODULES:
        print("✗ 实体个数与期望不符（§5 可能漏了一节，参照 ERR-0010）")
        ok = False

    if missing_in:
        ok = False
        print("✗ 发现 %d 个输入端口没有驱动源（悬空）：" % len(missing_in))
        for m, p, w in missing_in:
            print("    %s.%s（线名 %s）" % (m, p, w))
    else:
        print("✓ 全部 %d 个输入端口均有驱动源" % n_in)

    if orphan_out:
        ok = False
        print("✗ 发现 %d 个输出端口没有接收者：" % len(orphan_out))
        for m, p, w in orphan_out:
            print("    %s.%s（线名 %s）" % (m, p, w))
    else:
        print("✓ 全部 %d 个输出端口均有接收者（或为板级输出）" % n_out)

    print("-" * 64)
    print("输入端口 → 驱动源 对照表（供人工抽查）：")
    for m, p, w, s in input_rows:
        print("    %-16s %-18s ← %s" % (m + "." + p, w, s if s else "✗ 悬空"))
    return ok


def selftest(modules):
    """负向测试：注入两类假端口，必须都被检出（正例 = 无注入时通过）。"""
    import copy
    fake = copy.deepcopy(modules)

    # 反例 1：某模块多一个没有驱动源的输入
    fake["clk_gen"]["in"].append("i_ghost")
    # 反例 2：某模块多一个没有接收者的输出
    fake["clk_gen"]["out"].append("o_orphan")

    missing_in, orphan_out, _ = check(fake)
    ok = True
    if not any(p == "i_ghost" for _, p, _ in missing_in):
        print("✗ 自检失败：注入的悬空输入 i_ghost 未被检出")
        ok = False
    else:
        print("✓ 自检：注入的悬空输入 i_ghost 已检出")
    if not any(p == "o_orphan" for _, p, _ in orphan_out):
        print("✗ 自检失败：注入的无接收者输出 o_orphan 未被检出")
        ok = False
    else:
        print("✓ 自检：注入的无接收者输出 o_orphan 已检出")

    # 正例：未注入时应当全部通过
    m2, o2, _ = check(modules)
    if m2 or o2:
        print("✗ 自检失败：未注入时存在误报（正例不成立）")
        ok = False
    else:
        print("✓ 自检：未注入时零误报（正例成立）")
    return ok


def main():
    modules = parse_ports(DOC)
    if "--selftest" in sys.argv:
        return 0 if selftest(modules) else 1
    missing_in, orphan_out, input_rows = check(modules)
    return 0 if report(modules, missing_in, orphan_out, input_rows) else 1


if __name__ == "__main__":
    sys.exit(main())

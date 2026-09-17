#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vwf.py —— Quartus II 9.1 向量波形文件 (.vwf) 读写库

为什么需要这个库
----------------
本项目没有 ModelSim / GHDL，只能用 Quartus II 9.1 内置仿真器。该仿真器：

  1. 只能仿真**综合后网表**，不支持 VHDL 测试平台（没有 assert / testbench）；
  2. 没有提供任何 Tcl 命令接口（`::quartus::simulator` 是个空包）——
     已实测确认，无法用脚本驱动；
  3. 激励**只能**来自 .vwf 向量波形文件。

所以要做自动化验证，唯一的路是：**自己生成 .vwf 激励，自己解析 .vwf 结果**。
本库就是这条路的基础设施——相当于用 Python 写测试平台。

.vwf 文件格式（本库依据开发板上已验证过的真实 .vwf 逆向整理）
--------------------------------------------------------------
    HEADER { VERSION = 1; TIME_UNIT = ns; DATA_DURATION = 2000.0; ... }

    SIGNAL("clk")                 -- 每个节点一段
    { VALUE_TYPE = NINE_LEVEL_BIT; SIGNAL_TYPE = SINGLE_BIT;
      WIDTH = 1; LSB_INDEX = -1; DIRECTION = INPUT; PARENT = ""; }

    TRANSITION_LIST("clk")        -- 波形，嵌套 NODE / LEVEL 结构
    { NODE { REPEAT = 1;
             NODE { REPEAT = 100; LEVEL 0 FOR 10.0; LEVEL 1 FOR 10.0; } } }

    DISPLAY_LINE { CHANNEL = "clk"; ... }   -- 仅供波形窗口显示用
    TIME_BAR { TIME = 0; MASTER = TRUE; }
    ;

语义
----
  NODE  = 一串子项（子 NODE 或 LEVEL）**整体重复 REPEAT 次**
  LEVEL = "LEVEL <电平> FOR <持续时长>"，电平可以是 0/1/X/Z/…

仿真结果回写
------------
  quartus_sim <工程> --mode=functional --overwrite_waveform=on
  会把每个节点的仿真结果**写回输入 .vwf 的 TRANSITION_LIST**，
  于是本库的 parse() 可以直接读出仿真波形。这就是自动断言的基础。

位序约定与 rtl/puzzle_pkg.vhd 一致：
  mask(8*行 + 列)，列号向右递增，bit0 = 左上角

用法示例
--------
    import vwf
    b = vwf.Builder(duration=2000.0)
    b.clock("clk", period=20.0)
    b.segments("rst", [(100.0, 1), (1900.0, 0)])
    b.output_bus("q", 4)
    b.write("sim/demo.vwf")

    f = vwf.parse("sim/demo.vwf")
    for t, v in f.trace("q[0]"):
        print(t, v)
"""

import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TIME_UNIT = "ns"


# ============================================================
# 数据模型
# ============================================================

class Level:
    """波形叶子节点：保持某个电平一段时间。"""

    __slots__ = ("value", "duration")

    def __init__(self, value, duration):
        self.value = str(value).upper()
        self.duration = float(duration)

    def __repr__(self):
        return "Level(%s, %g)" % (self.value, self.duration)


class Node:
    """波形内部节点：一串子项整体重复 repeat 次。"""

    __slots__ = ("repeat", "children")

    def __init__(self, repeat=1, children=None):
        self.repeat = int(repeat)
        self.children = children if children is not None else []

    def __repr__(self):
        return "Node(repeat=%d, n=%d)" % (self.repeat, len(self.children))


class Signal:
    """一个节点（端口）的声明。"""

    __slots__ = ("name", "direction", "width", "parent")

    def __init__(self, name, direction, width=1, parent=""):
        self.name = name
        self.direction = direction.upper()
        self.width = int(width)
        self.parent = parent

    @property
    def is_bus(self):
        return self.width > 1

    @property
    def lsb_index(self):
        return 0 if self.is_bus else -1

    def __repr__(self):
        return "Signal(%s, %s, w=%d)" % (self.name, self.direction, self.width)


class VwfFile:
    """一个解析完成的 .vwf 文件。"""

    def __init__(self):
        self.time_unit = TIME_UNIT
        self.duration = 0.0
        self.grid_period = 10.0
        self.signals = {}       # name -> Signal
        self.order = []         # 信号出现顺序
        self.transitions = {}   # name -> Node

    def add_signal(self, sig):
        if sig.name not in self.signals:
            self.order.append(sig.name)
        self.signals[sig.name] = sig

    # ---------- 波形查询 ----------

    def expand(self, name):
        """
        把节点 name 的嵌套波形展开成 [(电平, 持续时长), ...]，按时序。
        """
        if name not in self.transitions:
            return []
        out = []
        _expand_node(self.transitions[name], out)
        return out

    def trace(self, name):
        """
        展开成 [(起始时刻, 电平), ...]，即每个电平变化的时刻与取值。
        电平字符串（如 'X'）原样保留。
        """
        seq = self.expand(name)
        out = []
        t = 0.0
        for value, dur in seq:
            if not out or out[-1][1] != value:
                out.append((t, value))
            t += dur
        return out

    def value_at(self, name, time):
        """求 name 在 time 时刻的电平（阶梯保持）。"""
        seq = self.expand(name)
        t = 0.0
        last = None
        for value, dur in seq:
            if time < t + dur:
                return value
            last = value
            t += dur
        return last

    def bus_value_at(self, name, time):
        """
        对总线取 time 时刻的整数值。
        name 传总线名（如 'q'），自动按 q[width-1..0] 拼位。
        任一位不是 0/1 则返回 None（表示含 X/Z）。
        """
        sig = self.signals.get(name)
        if sig is None or not sig.is_bus:
            raise KeyError("不是总线: %s" % name)
        val = 0
        for b in range(sig.width):
            bit_name = "%s[%d]" % (name, b)
            lv = self.value_at(bit_name, time)
            if lv not in ("0", "1"):
                return None
            if lv == "1":
                val |= (1 << b)
        return val


def _expand_node(node, out):
    """递归展开 Node，把 Level 追加到 out。"""
    for _ in range(node.repeat):
        for child in node.children:
            if isinstance(child, Level):
                out.append((child.value, child.duration))
            else:
                _expand_node(child, out)


# ============================================================
# 解析
# ============================================================

def _tokenize(text):
    """把 .vwf 切成 token；块注释 /* ... */ 直接丢弃。"""
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c == '"':
            j = text.find('"', i + 1)
            if j < 0:
                break
            tokens.append(("str", text[i + 1:j]))
            i = j + 1
            continue
        if c in "{};=(),":
            tokens.append(("sym", c))
            i += 1
            continue
        j = i
        while j < n and text[j] not in ' \t\r\n{};=(),"':
            j += 1
        tokens.append(("word", text[i:j]))
        i = j
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.pos = 0

    def peek(self):
        return self.toks[self.pos] if self.pos < len(self.toks) else (None, None)

    def next(self):
        t = self.peek()
        self.pos += 1
        return t

    def expect_sym(self, sym):
        kind, val = self.next()
        if val != sym:
            raise ValueError("期望 '%s'，实际遇到 %r" % (sym, val))

    def at_sym(self, sym):
        kind, val = self.peek()
        return kind == "sym" and val == sym


def _parse_kv_block(p):
    """读 { KEY = VALUE; ... }，返回 dict。"""
    out = {}
    p.expect_sym("{")
    while not p.at_sym("}"):
        kind, key = p.next()
        if key is None:
            break
        if kind == "sym" and key == ";":
            continue
        key = key.upper()
        if p.at_sym("="):
            p.next()
            _, val = p.next()
            out[key] = val
            if p.at_sym(";"):
                p.next()
        elif p.at_sym("{"):
            # 嵌套块（本格式中未用到，跳过）
            _parse_kv_block(p)
        else:
            p.next()
    p.expect_sym("}")
    return out


def _parse_node(p):
    """递归解析 NODE 块。"""
    node = Node(repeat=1)
    p.expect_sym("{")
    while not p.at_sym("}"):
        kind, tok = p.next()
        if tok is None:
            break
        if kind == "sym" and tok == ";":
            continue
        up = str(tok).upper()
        if up == "REPEAT":
            if p.at_sym("="):
                p.next()
            _, val = p.next()
            node.repeat = int(float(val))
            if p.at_sym(";"):
                p.next()
        elif up == "NODE":
            node.children.append(_parse_node(p))
        elif up == "LEVEL":
            _, value = p.next()
            # 下一个应当是 FOR
            if p.peek()[1] is not None and str(p.peek()[1]).upper() == "FOR":
                p.next()
            _, dur = p.next()
            if p.at_sym(";"):
                p.next()
            node.children.append(Level(value, dur))
        else:
            # 未知关键字，跳过到分号
            while not p.at_sym(";") and not p.at_sym("}") and p.peek()[0] is not None:
                p.next()
            if p.at_sym(";"):
                p.next()
    p.expect_sym("}")
    return node


def parse(path):
    """读取一个 .vwf 文件，返回 VwfFile。"""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    p = _Parser(_tokenize(text))
    vf = VwfFile()

    while p.peek()[0] is not None:
        kind, tok = p.next()
        if kind == "sym" and tok == ";":
            continue
        if kind != "word":
            continue
        head = tok.upper()

        if head == "HEADER":
            kv = _parse_kv_block(p)
            vf.time_unit = kv.get("TIME_UNIT", TIME_UNIT)
            vf.duration = float(kv.get("DATA_DURATION", 0.0))
            vf.grid_period = float(kv.get("GRID_PERIOD", 10.0))

        elif head in ("SIGNAL", "TRANSITION_LIST"):
            if p.at_sym("("):
                p.next()
            _, name = p.next()
            if p.at_sym(")"):
                p.next()
            if head == "SIGNAL":
                kv = _parse_kv_block(p)
                vf.add_signal(Signal(
                    name,
                    kv.get("DIRECTION", "INPUT"),
                    int(float(kv.get("WIDTH", 1))),
                    kv.get("PARENT", ""),
                ))
            else:
                vf.transitions[name] = _parse_node(p)

        elif head in ("DISPLAY_LINE", "TIME_BAR"):
            _parse_kv_block(p)

        else:
            if p.at_sym("{"):
                _parse_kv_block(p)
            elif p.at_sym(";"):
                p.next()

    return vf


# ============================================================
# 生成
# ============================================================

def _merge(segments):
    """合并相邻的相同电平，缩短波形描述。"""
    out = []
    for dur, lv in segments:
        dur = float(dur)
        if dur <= 0:
            continue
        lv = str(lv).upper()
        if out and out[-1][1] == lv:
            out[-1] = (out[-1][0] + dur, lv)
        else:
            out.append((dur, lv))
    return out


class Builder:
    """
    构建一个激励 .vwf。

    典型用法：
        b = Builder(duration=100000.0)     # 单位 ns
        b.clock("clk", period=20.0)        # 50MHz
        b.segments("sw7", [(2000.0, 0), (98000.0, 1)])
        b.output_bus("seg", 8)
        b.write("sim/xxx.vwf")
    """

    def __init__(self, duration, grid_period=10.0, time_unit=TIME_UNIT):
        self.duration = float(duration)
        self.grid_period = float(grid_period)
        self.time_unit = time_unit
        self.vf = VwfFile()
        self.vf.duration = self.duration
        self.vf.grid_period = self.grid_period
        self.vf.time_unit = time_unit
        self._pending = []      # [(name, [Node...])] 待写入的 TRANSITION_LIST

    # ---------- 声明节点 ----------

    def _declare_bus(self, name, width, direction):
        self.vf.add_signal(Signal(name, direction, width, ""))
        for b in range(width):
            self.vf.add_signal(
                Signal("%s[%d]" % (name, b), direction, 1, name))

    def input_bit(self, name):
        self._declare_bus(name, 1, "INPUT")

    def output_bit(self, name):
        self._declare_bus(name, 1, "OUTPUT")

    def input_bus(self, name, width):
        self._declare_bus(name, width, "INPUT")

    def output_bus(self, name, width):
        self._declare_bus(name, width, "OUTPUT")

    # ---------- 驱动波形 ----------

    def _set(self, name, node):
        self.vf.transitions[name] = node
        self._pending.append(name)

    def _segments_to_node(self, segments):
        """把 [(时长, 电平), ...] 变成一个 REPEAT=1 的 NODE。"""
        node = Node(repeat=1)
        for dur, lv in _merge(segments):
            node.children.append(Level(lv, dur))
        return node

    def segments(self, name, segments):
        """驱动一个单比特信号：segments = [(持续时长, 电平), ...]。"""
        self._set(name, self._segments_to_node(segments))

    def bus_segments(self, name, segments):
        """
        驱动一个总线：segments = [(持续时长, 整数值), ...]。
        自动拆成逐比特波形（值必须是整数；负值按位取反语义不适用）。
        """
        sig = self.vf.signals[name]
        width = sig.width
        # 先按位拆开
        per_bit = [[] for _ in range(width)]
        for dur, val in segments:
            if isinstance(val, str):
                raise ValueError("总线 %s 的值必须是整数，不能是 %r" % (name, val))
            for b in range(width):
                per_bit[b].append((dur, (int(val) >> b) & 1))
        for b in range(width):
            self._set("%s[%d]" % (name, b),
                      self._segments_to_node(_merge(per_bit[b])))

    def clock(self, name, period, duty=0.5, phase_low=True, start_low=True):
        """
        生成时钟。period 单位与 time_unit 一致（默认 ns）。
        用嵌套 REPEAT 压缩，避免上万行 LEVEL。
        默认低电平起始、50% 占空比。
        """
        period = float(period)
        high = period * (1.0 - duty) if not phase_low else period * duty
        high = period * duty
        low = period - high
        full = int(self.duration // period)
        rest = self.duration - full * period

        inner = Node(repeat=max(full, 1))
        first = "1" if not start_low else "0"
        second = "0" if first == "1" else "1"
        inner.children.append(Level(first, low if first == "0" else high))
        inner.children.append(Level(second, high if first == "0" else low))

        outer = Node(repeat=1)
        inner.repeat = max(full, 1)
        outer.children.append(inner)
        if rest > 1e-9:
            outer.children.append(Level(first, rest))
        self._set(name, outer)

    def bus_clock(self, name, period, width, duty=0.5):
        """总线计数器：每个周期 +1（用于给 ROM/LFSR 之类喂地址）。"""
        period = float(period)
        count = max(int(self.duration // period), 1)
        segs = [(period, i & ((1 << width) - 1)) for i in range(count)]
        rest = self.duration - count * period
        if rest > 1e-9:
            segs.append((rest, count & ((1 << width) - 1)))
        self.bus_segments(name, segs)

    def hold(self, name, level):
        """整个仿真时长保持某个电平（输出一般保持 'X'）。"""
        self._set(name, self._segments_to_node([(self.duration, level)]))

    # ---------- 输出 ----------

    def write(self, path):
        """把当前描述写成 .vwf 文件。"""
        # 未被驱动的输入/输出补默认波形
        for name in self.vf.order:
            sig = self.vf.signals[name]
            if sig.is_bus:
                continue
            if name not in self.vf.transitions:
                self.hold(name, "X" if sig.direction == "OUTPUT" else "0")

        L = []
        L.append("/*")
        L.append("    本文件由 scripts/vwf.py 自动生成 —— 请勿手工编辑。")
        L.append("    重新生成: python scripts/gen_stim.py")
        L.append("*/")
        L.append("")
        L.append("HEADER")
        L.append("{")
        L.append("\tVERSION = 1;")
        L.append("\tTIME_UNIT = %s;" % self.time_unit)
        L.append("\tDATA_OFFSET = 0.0;")
        L.append("\tDATA_DURATION = %s;" % _num(self.duration))
        L.append("\tSIMULATION_TIME = 0.0;")
        L.append("\tGRID_PHASE = 0.0;")
        L.append("\tGRID_PERIOD = %s;" % _num(self.grid_period))
        L.append("\tGRID_DUTY_CYCLE = 50;")
        L.append("}")
        L.append("")

        for name in self.vf.order:
            sig = self.vf.signals[name]
            L.append('SIGNAL("%s")' % name)
            L.append("{")
            L.append("\tVALUE_TYPE = NINE_LEVEL_BIT;")
            L.append("\tSIGNAL_TYPE = %s;" % ("BUS" if sig.is_bus else "SINGLE_BIT"))
            L.append("\tWIDTH = %d;" % sig.width)
            L.append("\tLSB_INDEX = %d;" % sig.lsb_index)
            L.append("\tDIRECTION = %s;" % sig.direction)
            L.append('\tPARENT = "%s";' % sig.parent)
            L.append("}")
            L.append("")

        for name in self.vf.order:
            if name not in self.vf.transitions:
                continue
            L.append('TRANSITION_LIST("%s")' % name)
            L.append("{")
            _emit_node(self.vf.transitions[name], L, 1)
            L.append("}")
            L.append("")

        # DISPLAY_LINE：TREE_INDEX 必须连续，CHILDREN/PARENT 必须自洽，
        # 否则仿真器会报 "corrupted display information" 警告。
        idx = {}
        for i, name in enumerate(self.vf.order):
            idx[name] = i
        for i, name in enumerate(self.vf.order):
            sig = self.vf.signals[name]
            L.append("DISPLAY_LINE")
            L.append("{")
            L.append('\tCHANNEL = "%s";' % name)
            L.append("\tEXPAND_STATUS = COLLAPSED;")
            L.append("\tRADIX = %s;" % ("Hexadecimal" if sig.is_bus else "Binary"))
            L.append("\tTREE_INDEX = %d;" % i)
            L.append("\tTREE_LEVEL = %d;" % (1 if sig.parent else 0))
            if sig.parent:
                L.append("\tPARENT = %d;" % idx[sig.parent])
            kids = [idx[n] for n in self.vf.order
                    if self.vf.signals[n].parent == name]
            if kids:
                L.append("\tCHILDREN = %s;" % ", ".join(str(k) for k in kids))
            L.append("}")
            L.append("")

        L.append("TIME_BAR")
        L.append("{")
        L.append("\tTIME = 0;")
        L.append("\tMASTER = TRUE;")
        L.append("}")
        L.append(";")
        L.append("")

        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(L))


def _num(x):
    """Altera 用 '2000.0' 这种带小数点的写法，保持一致的文本形式。"""
    return "%.1f" % float(x)


def _emit_node(node, L, depth):
    ind = "\t" * depth
    L.append(ind + "NODE")
    L.append(ind + "{")
    L.append(ind + "\tREPEAT = %d;" % node.repeat)
    for child in node.children:
        if isinstance(child, Level):
            L.append("%s\tLEVEL %s FOR %s;" % (ind, child.value, _num(child.duration)))
        else:
            _emit_node(child, L, depth + 1)
    L.append(ind + "}")


# ============================================================
# 命令行自检
# ============================================================

def _selftest():
    import tempfile
    import os

    path = os.path.join(tempfile.gettempdir(), "_vwf_selftest.vwf")
    b = Builder(duration=2000.0)
    b.input_bit("clk")
    b.clock("clk", period=20.0)
    b.input_bit("rst")
    b.segments("rst", [(100.0, 1), (1900.0, 0)])
    b.input_bus("sw", 4)
    b.bus_segments("sw", [(1000.0, 0x5), (1000.0, 0xA)])
    b.output_bus("q", 4)
    b.output_bit("y")
    b.write(path)

    f = parse(path)
    assert f.duration == 2000.0, f.duration
    assert f.signals["sw"].width == 4
    assert f.signals["sw"].is_bus
    assert not f.signals["sw[0]"].is_bus

    # 时钟：20ns 周期，2000/20 = 100 个完整周期
    tr = f.trace("clk")
    assert tr[0] == (0.0, "0"), tr[0]
    assert tr[1] == (10.0, "1"), tr[1]
    total = sum(d for _, d in f.expand("clk"))
    assert abs(total - 2000.0) < 1e-6, total

    # rst：100ns 高，之后低
    assert f.value_at("rst", 50.0) == "1"
    assert f.value_at("rst", 500.0) == "0"

    # 总线
    assert f.bus_value_at("sw", 500.0) == 0x5
    assert f.bus_value_at("sw", 1500.0) == 0xA

    # 输出默认 X
    assert f.value_at("y", 300.0) == "X"

    os.remove(path)
    print("vwf.py 自检通过 ✓")


if __name__ == "__main__":
    _selftest()

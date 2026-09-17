#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_tiling.py —— 拼图图案与零片分解的穷举验证脚本

用途
----
在冻结任何图案常量之前，必须先跑这个脚本，确认：
  1. 零片格数之和 == 目标图案格数
  2. 至少存在一种合法铺法（否则设计有误）
  3. 共有几种合法铺法 —— 这直接决定"成功判定"该怎么写

为什么重要
----------
第一关的三块零片恰好有 2 种合法铺法。若把成功判定写成
"每块零片回到各自初始位置"，就会把其中一种正确铺法误判为失败。
因此判定必须是 "并集 == 目标掩码"，本脚本就是这条结论的证据。

位序约定（与 rtl/puzzle_pkg.vhd 严格一致）
------------------------------------------
  mask(8*行 + 列)          列号向右递增；bit0 = 左上角
  第 r 行 = mask(8*r+7 downto 8*r)；行内 bit0 = 最左列、bit7 = 最右列
  「向右移一列」= 行向量左移：r(6 downto 0) & '0'

用法
----
    python scripts/verify_tiling.py
退出码非 0 表示验证失败（可用于 CI / 提交前检查）。
"""

import sys

# Windows 控制台默认是 GBK，强制走 UTF-8，否则中文输出乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ============================================================
# 基础工具
# ============================================================

ROWS = COLS = 8


def cells_to_mask(cells):
    """把 {(行,列)} 集合转成 64 位整数掩码。"""
    m = 0
    for r, c in cells:
        m |= 1 << (8 * r + c)
    return m


def mask_to_rows(m):
    """把 64 位掩码转成 8 个 8 位行掩码，行内 bit0 = 最左列。"""
    return [(m >> (8 * r)) & 0xFF for r in range(ROWS)]


def render(m, on="█", off="·"):
    """把掩码渲染成 8 行文本，便于人工核对。"""
    out = []
    for r in range(ROWS):
        row = (m >> (8 * r)) & 0xFF
        out.append("".join(on if (row >> c) & 1 else off for c in range(COLS)))
    return out


def mask_to_vhdl(m):
    """
    生成 VHDL 常量字面量（64 位二进制串）。
    按 行7…行0 从高到低拼接，与 mask(63 downto 0) 一一对应；
    每 8 位一组的行内，最高位是列0（最左列）。
    """
    row_masks = mask_to_rows(m)
    return "".join(format(row_masks[r], "08b") for r in range(ROWS - 1, -1, -1))


def normalize(shape):
    """把零片形状平移到左上角对齐（锚点原点）。"""
    min_r = min(r for r, _ in shape)
    min_c = min(c for _, c in shape)
    return frozenset((r - min_r, c - min_c) for r, c in shape)


def all_placements(shape):
    """
    枚举零片在 8x8 内的全部合法摆放，返回 {锚点(行,列): frozenset(绝对格)}。
    锚点是零片包围盒左上角在点阵上的位置。
    这里天然保证了"零片不出界"，即不变量 行+高<=8 且 列+宽<=8。
    """
    shape = normalize(shape)
    h = max(r for r, _ in shape) + 1
    w = max(c for _, c in shape) + 1
    out = {}
    for ar in range(ROWS - h + 1):
        for ac in range(COLS - w + 1):
            out[(ar, ac)] = frozenset((ar + r, ac + c) for r, c in shape)
    return out


def enumerate_tilings(target, pieces):
    """
    穷举所有合法铺法：每块零片恰好用一次，两两不重叠，并集 == 目标。
    返回 (铺法列表, 每种铺法下各零片的锚点元组)。
    """
    n = len(pieces)
    placement_tables = []
    for shp in pieces:
        # 只保留完全落在目标内的摆法，大幅剪枝
        tbl = {anc: cs for anc, cs in all_placements(shp).items() if cs <= target}
        placement_tables.append(tbl)

    solutions = []

    def rec(idx, used, chosen):
        if idx == n:
            if used == target:
                solutions.append(tuple(chosen))
            return
        for anc, cs in placement_tables[idx].items():
            if cs & used:
                continue
            chosen.append(anc)
            rec(idx + 1, used | cs, chosen)
            chosen.pop()

    rec(0, frozenset(), [])
    return solutions, placement_tables


# ============================================================
# 图案与零片定义
# ============================================================

def rect(r0, r1, c0, c1):
    return frozenset((r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1))


def from_rows(rows):
    """用字符串行描述图案，'X' 或 '#' 表示亮。"""
    return frozenset(
        (r, c)
        for r, line in enumerate(rows)
        for c, ch in enumerate(line)
        if ch in "X#"
    )


def from_shape(shape):
    """用字符串行描述零片形状（会自动左上角对齐）。"""
    return normalize(from_rows(shape))


# ---------- 第一关（题目指定，不可更改）----------

L1_TARGET = rect(2, 5, 2, 4)          # 第2~5行 x 第2~4列 实心 4x3 矩形

L1_PIECES = [
    from_shape(["XXX",
                "XX.",
                "X.."]),              # 零片1: 6 格
    from_shape([".X",
                "XX"]),               # 零片2: 3 格
    from_shape(["XXX"]),              # 零片3: 3 格
]

L1_NAMES = ["零片1(6格)", "零片2(3格)", "零片3(3格)"]

# ---------- 第二关（自拟：向上箭头）----------

L2_TARGET = from_rows([
    "........",
    "...XX...",
    "..XXXX..",
    ".XXXXXX.",
    "...XX...",
    "...XX...",
    "...XX...",
    "........",
])

L2_PIECES = [
    from_shape(["..X",
                ".XX",
                "XXX"]),              # 6 格（三角左半，阶梯）
    from_shape(["X..",
                "XX.",
                "XXX"]),              # 6 格（三角右半，阶梯，与上块镜像）
    from_shape(["XX",
                "XX"]),               # 4 格（2x2 方块）
    from_shape(["XX"]),               # 2 格（1x2 长条）
]

L2_NAMES = ["零片0(6格)", "零片1(6格)", "零片2(4格)", "零片3(2格)"]

# ---------- 向下箭头（第二关的第二套图案，用于"多图案随机"）----------

L2B_TARGET = from_rows([
    "........",
    "...XX...",
    "...XX...",
    "...XX...",
    ".XXXXXX.",
    "..XXXX..",
    "...XX...",
    "........",
])

# 向下箭头 = 向上箭头上下翻转，零片形状同步翻转
L2B_PIECES = [
    from_shape(["XXX",
                "XX.",
                "X.."]),
    from_shape(["XXX",
                ".XX",
                "..X"]),
    from_shape(["XX",
                "XX"]),
    from_shape(["XX"]),
]


# ============================================================
# 验证
# ============================================================

def check(name, target, pieces, names, vhdl_name):
    print("=" * 62)
    print("【%s】" % name)
    print("=" * 62)

    tcount = len(target)
    pcount = sum(len(p) for p in pieces)

    print("目标图案 (%d 格):" % tcount)
    for line in render(cells_to_mask(target), "██", "··"):
        print("   ", line)

    print("\n零片形状:")
    for nm, p in zip(names, pieces):
        h = max(r for r, _ in p) + 1
        w = max(c for _, c in p) + 1
        print("  %s  (%d 格, 包围盒 %d行 x %d列)" % (nm, len(p), h, w))
        for r in range(h):
            print("      " + "".join(
                "██" if (r, c) in p else "··" for c in range(w)))

    ok = True

    # 检查 1: 格数守恒
    if pcount != tcount:
        print("\n✗ 格数不守恒: 零片合计 %d 格, 目标 %d 格" % (pcount, tcount))
        ok = False
    else:
        print("\n✓ 格数守恒: %d == %d" % (pcount, tcount))

    # 检查 2/3: 穷举铺法
    sols, _ = enumerate_tilings(target, pieces)

    if not sols:
        print("✗ 无解！这套零片铺不出目标图案，图案或分解需要重新设计")
        ok = False
    else:
        print("✓ 合法铺法共 %d 种" % len(sols))
        for i, sol in enumerate(sols, 1):
            print("  --- 铺法 %d: 零片锚点(行,列) = %s ---" % (i, list(sol)))
            canvas = {}
            for k, (ar, ac) in enumerate(sol):
                shp = pieces[k]
                for r, c in shp:
                    canvas[(ar + r, ac + c)] = str(k)
            for r in range(ROWS):
                line = "".join(canvas.get((r, c), "·") for c in range(COLS))
                print("      " + line)

        if len(sols) >= 2:
            print("\n  ⚠ 存在 %d 种合法铺法 —— 成功判定必须是「并集 == 目标」！" % len(sols))
            print("    绝不能写成「每块回到各自初始位置」，否则会误判正确铺法为失败。")
        else:
            print("\n  只有唯一铺法；仍建议用「并集 == 目标」判定（更通用）。")

    # 输出可直接粘贴进 puzzle_pkg.vhd 的常量
    print("\n目标图案 mask 常量 (VHDL, 高位=行7 … 低位=行0):")
    print('    constant %s : std_logic_vector(63 downto 0) :=' % vhdl_name)
    print('        "%s";' % mask_to_vhdl(cells_to_mask(target)))

    print()
    return ok


def main():
    results = []
    results.append(check("第一关 · 实心4x3矩形", L1_TARGET, L1_PIECES, L1_NAMES,
                         "L1_TARGET_MASK"))
    results.append(check("第二关 · 向上箭头", L2_TARGET, L2_PIECES, L2_NAMES,
                         "L2_TARGET_MASK"))
    results.append(check("第二关备选 · 向下箭头", L2B_TARGET, L2B_PIECES, L2_NAMES,
                         "L2B_TARGET_MASK"))

    print("=" * 62)
    if all(results):
        print("全部验证通过 ✓")
        return 0
    print("存在验证失败项 ✗")
    return 1


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""
check_pins.py —— 引脚分配一致性检查

【为什么需要这个脚本】
引脚号是本项目唯一"抄错一个数字就全盘报废、且仿真完全查不出来"的东西：
    · 抄错了不会报错，Quartus 照样编译通过；
    · 仿真时引脚号根本用不上（仿的是逻辑，不是管脚）；
    · 只有上板才发现，而板子只在实验室能用。
所以必须用程序把"手册"和".qsf"钉死在一起做逐条比对，而不是靠人眼。

【三层数据来源】
    ① 本文件的 EXPECTED 表 —— 逐条抄自开发板手册（唯一权威）
    ② quartus/puzzle.qsf      —— 实际生效的约束
    ③ docs/04-引脚分配表.md    —— 给人看的文档（用 --markdown 生成表格片段）

本脚本比对 ① 与 ②。三者不一致时，以 ① 为准。

【用法】
    python scripts/check_pins.py              # 比对，打印结论
    python scripts/check_pins.py --markdown   # 额外输出 Markdown 表格（粘进 docs/04）

【历史教训】
    本机桌面上另一个旧工程把 col_r[0] 接到了 PIN_11（= 手册里的 COLR7），
    与手册恰好相反。那个工程自身是自洽的，但引脚表已不对应板上丝印。
    → 见 ERRORS.md ERR-0003。结论：引脚号只认手册，旧工程只能用来
      交叉验证"用到了哪些引脚"，不能用来确定位序。
"""

import re
import sys
import pathlib

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
QSF = ROOT / "quartus" / "puzzle.qsf"


# ============================================================
# ① 权威表：逐条抄自《MAXII数字实验板（LCM12864液晶版）》开发板手册
#    格式: 信号名(不含位下标) -> (起始位, 手册原文的引脚号序列, 有效电平说明)
# ============================================================
EXPECTED = {
    "clk": dict(pins=[18], note="全局时钟，板载档位 7 = 50MHz"),

    "sw7": dict(pins=[125], note="系统开关，高=开"),

    "dot_row": dict(
        pins=[8, 7, 6, 5, 4, 3, 2, 1],
        note="点阵行 ROW0~ROW7，**低有效**"),

    "dot_colr": dict(
        pins=[22, 21, 16, 15, 14, 13, 12, 11],
        note="点阵红列 COLR0~COLR7，高有效。"
             "★ 手册原文：COLR0~COLR7 依次使用 22、21、16、15、14、13、12 和 11 脚"),

    "dot_colg": dict(
        pins=[45, 44, 43, 42, 41, 40, 39, 38],
        note="点阵绿列 COLG0~COLG7，高有效"),

    "seg": dict(
        pins=[62, 59, 58, 57, 55, 53, 52, 51],
        note="段 AA,AB,AC,AD,AE,AF,AG,AP，高有效"),

    "cat": dict(
        pins=[63, 66, 67, 68, 69, 70, 30, 31],
        note="位选 CAT0~CAT7，**低有效**。CAT0→DISP0(最右) … CAT7→DISP7(最左)"),

    "kp_col": dict(
        pins=[117, 118, 119, 120],
        note="键盘列 COL0~COL3，扫描输出（逐列驱动为高）"),

    "kp_row": dict(
        pins=[111, 112, 113, 114],
        note="键盘行 ROW0~ROW3，读入，**按下 = '1'**。实物 ROW3 在最上排"),

    "buzz": dict(pins=[60], note="蜂鸣器，音频方波"),

    "ld": dict(
        pins=[80, 79, 78, 77, 76, 75, 74, 73, 144, 143, 142, 141, 140, 139, 138, 137],
        note="LD0~LD15，**高电平点亮**"),
}

# 板上必需、但本项目未使用的引脚（列出来是为了让检查报告更完整）
UNUSED_NOTE = [
    "液晶 LCM12864 相关引脚：本项目不使用",
    "PS/2、串口等外设引脚：本项目不使用",
]


# ============================================================
# ② 解析 .qsf
# ============================================================
def parse_qsf(path):
    """返回 {信号全名: 引脚号}，例如 {'dot_row[0]': 8, ...}"""
    text = path.read_text(encoding="utf-8", errors="replace")
    result = {}
    for m in re.finditer(
        r'^\s*set_location_assignment\s+PIN_(\d+)\s+-to\s+(\S+)\s*$',
        text, re.MULTILINE):
        result[m.group(2)] = int(m.group(1))
    return result


def expected_flat():
    """把 EXPECTED 展开成 {信号全名: 期望引脚号}"""
    flat = {}
    for name, spec in EXPECTED.items():
        for i, pin in enumerate(spec["pins"]):
            key = name if len(spec["pins"]) == 1 else f"{name}[{i}]"
            flat[key] = pin
    return flat


# ============================================================
# ③ 比对
# ============================================================
def check():
    if not QSF.exists():
        print(f"✗ 找不到 {QSF}")
        return 1

    actual = parse_qsf(QSF)
    want = expected_flat()

    missing = [k for k in want if k not in actual]
    extra = [k for k in actual if k not in want]
    wrong = [(k, want[k], actual[k]) for k in want
             if k in actual and actual[k] != want[k]]

    print("=" * 64)
    print("引脚分配一致性检查")
    print("=" * 64)
    print(f"权威表（手册）: {len(want)} 个引脚")
    print(f"实际约束(.qsf): {len(actual)} 个引脚")
    print()

    ok = True

    if wrong:
        ok = False
        print(f"✗ 引脚号不符（{len(wrong)} 处）:")
        for k, w, a in wrong:
            print(f"    {k:<14} 手册 = PIN_{w:<4} .qsf = PIN_{a}")
        print()

    if missing:
        ok = False
        print(f"✗ .qsf 中缺少（{len(missing)} 处）:")
        for k in missing:
            print(f"    {k:<14} 期望 PIN_{want[k]}")
        print()

    if extra:
        ok = False
        print(f"✗ .qsf 中多出（{len(extra)} 处，权威表里没有）:")
        for k in extra:
            print(f"    {k:<14} .qsf = PIN_{actual[k]}")
        print()

    if ok:
        print("✓ 全部一致：.qsf 与手册逐条吻合")
        print()

    # 逐组小结（无论对错都打印，方便人工复核）
    print("-" * 64)
    print(f"{'信号组':<12}{'位数':<6}{'手册引脚号':<44}{'结论'}")
    print("-" * 64)
    for name, spec in EXPECTED.items():
        n = len(spec["pins"])
        pins_str = ",".join(str(p) for p in spec["pins"])
        if n > 4:
            pins_str = pins_str[:38] + "…"
        group_ok = all(
            actual.get(name if n == 1 else f"{name}[{i}]") == p
            for i, p in enumerate(spec["pins"])
        )
        mark = "✓" if group_ok else "✗"
        print(f"{name:<12}{n:<6}{pins_str:<44}{mark}")
    print("-" * 64)

    # 引脚唯一性检查（同一引脚不能被分配两次）
    seen = {}
    dup = []
    for sig, pin in actual.items():
        if pin in seen:
            dup.append((pin, seen[pin], sig))
        seen[pin] = sig
    if dup:
        ok = False
        print()
        print("✗ 引脚冲突（同一引脚分配给了两个信号）:")
        for pin, a, b in dup:
            print(f"    PIN_{pin}: {a} 与 {b}")
    else:
        print(f"✓ 引脚唯一性：{len(actual)} 个引脚无一重复")

    return 0 if ok else 1


def emit_markdown():
    """输出可直接粘进 docs/04 的 Markdown 表格"""
    print()
    print("=" * 64)
    print("Markdown 表格（复制到 docs/04-引脚分配表.md）")
    print("=" * 64)
    print()
    print("| 信号组 | 位宽 | 引脚号 | 有效电平 / 说明 |")
    print("|---|---|---|---|")
    for name, spec in EXPECTED.items():
        n = len(spec["pins"])
        pins = "、".join(f"`PIN_{p}`" for p in spec["pins"])
        sig = f"`{name}`" if n == 1 else f"`{name}[{n-1}:0]`"
        print(f"| {sig} | {n} | {pins} | {spec['note']} |")
    print()


def main():
    rc = check()
    if "--markdown" in sys.argv:
        emit_markdown()
    return rc


if __name__ == "__main__":
    sys.exit(main())

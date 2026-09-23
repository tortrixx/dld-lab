# -*- coding: utf-8 -*-
"""set_top.py —— 在 `board_test_top`（硬件自检）与 `puzzle_top`（整机拼图）之间切换顶层

【为什么需要它】
    工程只有一个顶层，而两个顶层**端口不同**：
      · `board_test_top` 有 `ld[15:0]`（16 个 LED），`puzzle_top` **没有**；
      · `quartus/puzzle.qsf` 里为这 16 个 LED 写了 16 行引脚约束。
    ⚠️ 只改 `TOP_LEVEL_ENTITY` 而**不注释掉那 16 行**，fitter 会报
       "引脚分配给不存在的端口"（`docs/02` §14.1.4 的"阶段 4 迁移三步"说的就是这件事）。
    手工要改 17 处，很容易漏一半 —— 这个脚本一次做对，并且可反复来回切。

【用法】
    python scripts/set_top.py board_test_top   # 切到硬件自检（含 16 个 LED）
    python scripts/set_top.py puzzle_top       # 切到整机拼图（自动注释 ld 约束）
    python scripts/set_top.py check            # 只报告当前是哪个顶层、ld 是否已注释
    python scripts/set_top.py puzzle_top --qsf <别的.qsf>   # 指定文件（测试/多工程用）

【安全设计】
    · 只改两处：`TOP_LEVEL_ENTITY` 一行 + `-to ld[…]` 那 16 行的行首 `# `；
    · **幂等**：已经是目标状态时什么都不做；
    · 本脚本**不写任何引脚号**（只按 `-to ld[` 匹配），引脚号的唯一真值源仍是 `.qsf` 本身；
    · 切完提示重新编译 —— 换顶层后必须重编，`.pof` 才会变成新顶层的。
"""

import pathlib
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_QSF = ROOT / "quartus" / "puzzle.qsf"

LD_RE = re.compile(r"^(\s*#\s*)?(set_location_assignment\s+PIN_\d+\s+-to\s+ld\[)")
TOP_RE = re.compile(r"^(set_global_assignment\s+-name\s+TOP_LEVEL_ENTITY\s+)(\S+)\s*$")


def read_qsf(path: pathlib.Path):
    return path.read_text(encoding="utf-8").split("\n")


def current(lines):
    top = "?"
    n_ld = n_ld_on = 0
    for ln in lines:
        m = TOP_RE.match(ln)
        if m:
            top = m.group(2)
        if LD_RE.match(ln):
            n_ld += 1
            if not LD_RE.match(ln).group(1):
                n_ld_on += 1
    return top, n_ld, n_ld_on


def do_check(lines) -> int:
    top, n_ld, n_ld_on = current(lines)
    print(f"  当前顶层 TOP_LEVEL_ENTITY = {top}")
    print(f"  ld 引脚约束：共 {n_ld} 行，其中 {n_ld_on} 行生效、{n_ld - n_ld_on} 行已注释")
    if top == "puzzle_top" and n_ld_on:
        print("  ✗ 顶层是 puzzle_top，但 ld 约束还生效 —— 编译会在 fitter 阶段报错！")
        return 1
    if top == "board_test_top" and n_ld_on != n_ld:
        print("  ✗ 顶层是 board_test_top，但 ld 约束被注释了 —— 16 个 LED 不会有引脚！")
        return 1
    print("  ✓ 两者一致")
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:]]
    qsf = DEFAULT_QSF
    if "--qsf" in args:
        i = args.index("--qsf")
        qsf = pathlib.Path(args[i + 1])
        del args[i:i + 2]

    if not qsf.exists():
        print(f"✗ 找不到 {qsf}")
        return 2
    lines = read_qsf(qsf)

    if not args or args[0] == "check":
        print("=" * 60)
        print(f"{qsf}")
        print("=" * 60)
        return do_check(lines)

    target = args[0]
    if target not in ("board_test_top", "puzzle_top"):
        print(__doc__)
        return 2

    # 整机顶层没有 ld 端口 → 注释掉那 16 行；自检顶层需要它们 → 放开
    want_ld = (target == "board_test_top")
    out, n_top, n_ld = [], 0, 0
    for ln in lines:
        m = TOP_RE.match(ln)
        if m:
            if m.group(2) != target:
                ln = m.group(1) + target
                n_top += 1
        else:
            m2 = LD_RE.match(ln)
            if m2:
                body = m2.group(2)
                hashed = m2.group(1) is not None
                if want_ld and hashed:            # 放开
                    ln = body
                    n_ld += 1
                elif (not want_ld) and (not hashed):   # 注释掉
                    ln = "# " + body
                    n_ld += 1
        out.append(ln)

    if n_top == 0 and n_ld == 0:
        print(f"  ✓ 已经是 {target} 的状态，无需改动")
        return 0

    qsf.write_text("\n".join(out), encoding="utf-8", newline="")
    print(f"  ✓ 顶层 → {target}（改 {n_top} 行）")
    print(f"  ✓ ld 引脚约束：{'放开' if want_ld else '注释掉'} {n_ld} 行")
    print()
    print("  ⚠️ 换顶层后必须**重新编译**，quartus/ 下的 .pof 才是新顶层的：")
    print("     GUI：Processing → Start Compilation")
    print("     命令行：quartus_sh --flow compile puzzle")
    print("  ⚠️ Quartus 开着工程时请先关掉工程，或改完在 Quartus 里选 Reload。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

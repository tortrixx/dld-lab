# -*- coding: utf-8 -*-
"""encoding.py —— rtl/*.vhd 的编码转换（UTF-8 ⇄ GBK）

【为什么需要这个脚本】
    Quartus II **11.0 及以下**（本项目用 9.1）的文本编辑器**固定按系统 ANSI
    （简体中文 = CP936/GBK）解码源文件**，且**没有"以指定编码打开"的选项**
    （那是 Quartus Prime 较新版本才有的 File → Open with Encoding）。
    于是"UTF-8 无 BOM"的 `.vhd` 里的中文注释会被当成 GBK 双字节解读 → 乱码。
    ⚠️ 这与 `CLAUDE.md` §5.4 里 PowerShell 5.1 按 ANSI 解码 UTF-8 文档是**同一个坑**：
       **"别的程序按 ANSI 读、你按 UTF-8 写" → 静默乱码，不报错。**

【裁决：只改 .vhd 的编码，其它一律保持 UTF-8】
    · `rtl/*.vhd` → **GBK**：Quartus 9.1 里能正常显示/编辑中文注释，
      且**不影响综合**（注释只是字节流，编译器只看到行尾）；
    · `docs/*.md` `*.py` `*.qsf` 等 → 仍 UTF-8（AI 工具、Grep、git 都按 UTF-8 处理）。
    ⚠️ **注意代价**：AI 工具（Write/Edit）产出的永远是 UTF-8 ——
      **每次用 AI 改完代码，必须重跑一次 `python scripts/encoding.py gbk`**，
      否则 Quartus 里又会乱码。这一条已写进 CLAUDE.md §5.4。

【用法】
    python scripts/encoding.py check     # 只报告当前编码，不改文件
    python scripts/encoding.py gbk       # UTF-8 → GBK（打开 Quartus 前跑）
    python scripts/encoding.py utf8      # GBK  → UTF-8（用 AI / 提交前跑）

【安全设计】
    · **往返安全校验**：转换前先确认"目标编码能完整表示原文"，
      有字符编不过去就**拒绝**（不会静默写成 '?'）；
    · **幂等**：已经是目标编码的文件不动；
    · **只碰 rtl/ 下的 .vhd**，不动任何文档与脚本。
"""

import pathlib
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
RTL = ROOT / "rtl"
SRC_ENC = {"utf8": "utf-8", "gbk": "gbk"}

# ============================================================
# GBK 无法表示的装饰符号 → GBK 安全等价物
#   只影响注释里的排版装饰，不改变任何语义。
#   ⚠️ 这张表是"实测扫出来的"：先跑 `encoding.py scan-bad` 得到清单，再往这里加。
#   若哪天新增了表外的不可编码字符，转换会**拒绝并报行内位置**，不会静默写成 '?'。
# ============================================================
GBK_SUBST = {
    "\u26a0": "\u203b",   # ⚠ → ※
    "\ufe0f": "",         # 变体选择符（⚠️ 的第二个码位）→ 直接删掉
    "\u2b50": "\u2605",   # ⭐ → ★（与代码里其它 ★ 标记保持一致）
    "\u00b5": "\u03bc",   # µ(U+00B5 微符号) → μ(U+03BC 希腊 mu)
    "\u2212": "-",        # −(数学减号) → -(ASCII 连字符)
    "\u2194": "<->",      # ↔ → <->
    "\u27fa": "\u5f53\u4e14\u4ec5\u5f53",  # ⟺ → 当且仅当
    "\u246a": "(11)",     # ⑪ → (11)
    "\u246b": "(12)",     # ⑫ → (12)
    "\u2713": "\u221a",   # ✓ → √（2026-09-24 补：keypad_scan 注释里用到）
    "\u2717": "\u00d7",   # ✗ → ×（同上）
}


def sanitize_for_gbk(text: str):
    """把 GBK 装不下的装饰符号换成等价物，返回 (新文本, 替换次数)。"""
    n = 0
    for bad, good in GBK_SUBST.items():
        c = text.count(bad)
        if c:
            text = text.replace(bad, good)
            n += c
    return text, n


def scan_bad() -> int:
    """列出当前 rtl/*.vhd 里 GBK 装不下的字符（新增符号时先跑这个）。

    ⚠️ 文件可能是 GBK（`encoding.py gbk` 之后的预期状态），
    必须按 detect() 的结果解码 —— 曾直接按 UTF-8 硬读而在 GBK 文件上崩溃。
    """
    import collections
    bad = collections.Counter()
    for p in vhd_files():
        raw = p.read_bytes()
        enc = detect(raw)
        if enc == "unknown":
            print(f"⚠️ {p.name}: 编码无法识别（既非 UTF-8 也非 GBK），跳过")
            continue
        text = raw.decode("utf-8" if enc == "utf8" else "gbk")
        for ch in text:
            if ord(ch) > 127:
                try:
                    ch.encode("gbk")
                except UnicodeEncodeError:
                    bad[ch] += 1
    if not bad:
        print("✓ 没有 GBK 装不下的字符，可直接转换。")
        return 0
    print("GBK 装不下的字符（需要在 GBK_SUBST 里给出替换）：")
    for ch, n in bad.most_common():
        known = "（表里已有）" if ch in GBK_SUBST else "⚠️ 表里没有，需新增"
        print(f"   U+{ord(ch):04X}  {ch!r}  x{n}  {known}")
    return 0


def detect(raw: bytes) -> str:
    """判断字节流的编码：先按 UTF-8 严格解码（更严格，误判率低），失败再按 GBK。"""
    try:
        raw.decode("utf-8")
        return "utf8"
    except UnicodeDecodeError:
        try:
            raw.decode("gbk")
            return "gbk"
        except UnicodeDecodeError:
            return "unknown"


def vhd_files():
    return sorted(RTL.glob("*.vhd"))


def do_check() -> int:
    print("=" * 66)
    print("rtl/*.vhd 当前编码")
    print("=" * 66)
    counts = {}
    for p in vhd_files():
        enc = detect(p.read_bytes())
        counts[enc] = counts.get(enc, 0) + 1
        print(f"  {p.name:<24} {enc}")
    print("-" * 66)
    print(f"  合计：{counts}")
    if counts.get("utf8") and counts.get("gbk"):
        print("  ⚠️ 混合编码！Quartus 9.1 只有一个默认解码方式，必须先统一。")
    print("  提示：Quartus II 9.1 里要正常显示中文注释 → 跑 `encoding.py gbk`")
    return 0


def convert(target: str) -> int:
    src_enc, dst_enc = SRC_ENC["utf8" if target == "gbk" else "gbk"], SRC_ENC[target]
    ok = skipped = subst = 0
    failed = []

    for p in vhd_files():
        raw = p.read_bytes()
        enc = detect(raw)
        if enc == "unknown":
            failed.append((p.name, "既不是 UTF-8 也不是 GBK"))
            continue
        if enc == target:
            skipped += 1
            continue

        # ① 解码 → ② 目标编码装不下的装饰符号先替换 → ③ 往返安全校验 → ④ 写回
        try:
            text = raw.decode(src_enc)
        except UnicodeDecodeError as e:
            failed.append((p.name, f"按 {src_enc} 解码失败：{e}"))
            continue
        if target == "gbk":
            text, n = sanitize_for_gbk(text)
            subst += n
        try:
            out = text.encode(dst_enc)
        except UnicodeEncodeError as e:
            # 仍有装不下的字符 → 拒绝，不静默替换成 '?'
            failed.append((p.name, f"按 {dst_enc} 编码失败（第 {e.start} 字符）：{e.reason}"
                                   f" —— 请把该字符加进 GBK_SUBST"))
            continue
        if out.decode(dst_enc) != text:
            failed.append((p.name, "往返校验不一致"))
            continue

        p.write_bytes(out)
        ok += 1
        print(f"  ✓ {p.name:<24} {enc} → {target}")

    print("-" * 66)
    print(f"  已转换 {ok} 个，已是 {target} 跳过 {skipped} 个，装饰符号替换 {subst} 处")
    if failed:
        print(f"  ✗ 失败 {len(failed)} 个（未改动，请人工处理）：")
        for name, why in failed:
            print(f"      {name}: {why}")
        return 1
    if target == "gbk":
        print("  现在可以用 Quartus II 9.1 打开工程，中文注释应显示正常。")
    else:
        print("  已回到 UTF-8（AI 工具 / Grep / git diff 都能正确读）。")
    return 0


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else "check"
    if arg == "check":
        return do_check()
    if arg == "scan-bad":
        return scan_bad()
    if arg in ("gbk", "utf8"):
        return convert(arg)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())

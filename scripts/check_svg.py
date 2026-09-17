#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_svg.py —— 内嵌 SVG 的三合一校验（浏览器里"能看"不等于"格式正确"）

背景见 ERRORS.md ERR-0004：图表 HTML 在浏览器里渲染正常，但导入 draw.io 会失败。
浏览器是宽容解析器，它渲染成功**不能证明文件合法**。本脚本补上这一步。

检查三件事：
  ① XML 是否合法              —— 注释里出现 `--` 会直接让严格解析器拒绝
  ② 每个绘制形状是否有显式填充 —— 漏了 fill 会渲染成黑色实心块
  ③ 是否还有会被 CSS 类覆盖的
     `stroke=` / `fill=` 属性   —— presentation attribute 特异性为 0，
                                  任何写了同名属性的 CSS 类都会压掉它

用法：
    python scripts/check_svg.py docs/图/系统图.html
    python scripts/check_svg.py docs/图/*.html  *.svg
退出码：0 = 全部通过，1 = 有问题
"""

import io
import re
import sys
import glob
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 会在 CSS 里定义 fill/stroke 的类名 —— 出现在这些类上的属性写法是安全的
FILL_CLASSES = {"dg-box", "dg-time", "dg-driver", "dg-data", "dg-region",
                "st", "st-box", "bar", "dot", "px"}
# 只定义 stroke、fill 固定为 none 的类
STROKE_ONLY_CLASSES = {"dg-wire", "dg-wire-fb", "wire", "link", "axis", "grid"}

SHAPES = {"rect", "path", "circle", "ellipse", "polygon", "polyline"}


def local(tag):
    """去掉 XML 命名空间，只留标签名"""
    return tag.split("}")[-1]


def extract_svgs(text):
    """从 HTML 或纯 SVF 文本里取出所有 <svg>…</svg> 块"""
    return re.findall(r"<svg\b.*?</svg>", text, re.S)


def check(path):
    """返回 (问题列表, 统计信息)"""
    try:
        text = io.open(path, encoding="utf-8").read()
    except OSError as e:
        return [f"读不到文件：{e}"], {}

    problems = []
    svgs = extract_svgs(text)
    if not svgs:
        return ["文件里没有找到 <svg> 块"], {}

    stats = {"svg": len(svgs), "shapes": 0, "colored_ok": 0}

    # ---------- ① XML 合法性 ----------
    for i, sv in enumerate(svgs, 1):
        try:
            ET.fromstring(sv)
        except ET.ParseError as e:
            line = getattr(e, "position", (0, 0))[0]
            snippet = sv.split("\n")[line - 1].strip()[:70] if line else ""
            problems.append(
                f"SVG #{i} XML 不合法：{e}\n"
                f"        ↳ 该行：{snippet}\n"
                f"        ↳ 最常见原因：XML 注释里出现了连续两个连字符 `--`"
            )

    # 注释里的 `--`（单独报一次，比 XML 报错更直白）
    for m in re.finditer(r"<!--(.*?)-->", text, re.S):
        if "--" in m.group(1):
            ln = text[: m.start()].count("\n") + 1
            problems.append(
                f"第 {ln} 行注释体里含 `--`（XML 禁止）"
                f"：{m.group(0)[:60]}"
            )

    # ---------- ② 显式填充 & ③ 会被覆盖的属性 ----------
    for i, sv in enumerate(svgs, 1):
        try:
            root = ET.fromstring(sv)
        except ET.ParseError:
            continue  # ① 已报过

        for el in root.iter():
            if local(el.tag) not in SHAPES:
                continue
            stats["shapes"] += 1
            a = el.attrib
            cls = set(a.get("class", "").split())
            style = a.get("style", "")

            has_fill = ("fill" in a) or ("fill" in style) \
                or bool(cls & FILL_CLASSES) or bool(cls & STROKE_ONLY_CLASSES)
            if not has_fill:
                problems.append(
                    f"SVG #{i} 的 <{local(el.tag)}> 没有显式填充"
                    f"（class={a.get('class', '—')}）→ 会渲染成黑色实心块"
                )
            else:
                stats["colored_ok"] += 1

            # presentation attribute 会被同名 CSS 类属性压掉
            for prop in ("stroke", "fill"):
                if prop in a and cls & (FILL_CLASSES | STROKE_ONLY_CLASSES):
                    problems.append(
                        f"SVG #{i} 的 <{local(el.tag)} class=\"{' '.join(cls)}\"> "
                        f"用了 `{prop}=\"{a[prop]}\"` 属性 —— "
                        f"类规则里有同名属性时会覆盖它（特异性为 0）。"
                        f"改用 style=\"{prop}:{a[prop]}\""
                    )

    # ---------- 箭头 marker 是否有显式填充 ----------
    ids = set(re.findall(r'\bid="([^"]+)"', text))
    refs = set(re.findall(r'marker-end="url\(#([^)]+)\)"', text))
    for r in refs - ids:
        problems.append(f"marker-end 引用了不存在的 id：#{r}")

    # ---------- 跨 SVG 的 id 冲突（同页多图常见）----------
    all_ids = re.findall(r'\bid="([^"]+)"', text)
    dup = {x for x in all_ids if all_ids.count(x) > 1}
    if dup:
        problems.append(
            f"id 重复 {sorted(dup)} —— 同一页多张 SVG 的 id 必须互不冲突，"
            f"否则 marker/渐变会串图"
        )

    return problems, stats


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2

    targets = []
    for pat in argv[1:]:
        hits = glob.glob(pat)
        targets.extend(hits if hits else [pat])

    total = 0
    for path in targets:
        problems, stats = check(path)
        print(f"\n=== {path}")
        if stats:
            print(f"    内嵌 SVG {stats['svg']} 张，绘制形状 {stats['shapes']} 个")
        if problems:
            total += len(problems)
            for p in problems:
                print(f"    ✗ {p}")
        else:
            print("    ✓ XML 合法 · 填充完整 · 无属性覆盖 · id 无冲突")

    print(f"\n{'=' * 52}")
    if total:
        print(f"共 {total} 个问题，详见 ERRORS.md ERR-0004")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

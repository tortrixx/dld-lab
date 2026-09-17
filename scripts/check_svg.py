#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_svg.py —— 内嵌 SVG 的三合一校验（浏览器里"能看"不等于"格式正确"）

背景见 ERRORS.md ERR-0004：图表 HTML 在浏览器里渲染正常，但导入 draw.io 会失败。
浏览器是宽容解析器，它渲染成功**不能证明文件合法**。本脚本补上这一步。

检查四件事：
  ① XML 是否合法              —— 注释里出现 `--` 会直接让严格解析器拒绝
  ② 每个绘制形状是否有显式填充 —— 漏了 fill 会渲染成黑色实心块
  ③ 是否还有会被 CSS 类覆盖的
     `stroke=` / `fill=` 属性   —— presentation attribute 特异性为 0，
                                  任何写了同名属性的 CSS 类都会压掉它
  ④ 走线是否横穿方框           —— 连线从方框内部穿过，图就废了，
                                  而这种错误浏览器里照样"渲染成功"（见 ERR-0006）

② ③ 的判据**直接从 <style> 块里解析出"每个类声明了哪些属性"**，
不维护类名白名单——否则样式表里每加一个新类，脚本就会误报（见 ERRORS.md ERR-0005）。

④ 只判定**轴对齐**的线段（水平/垂直），也就是本项目框图里实际使用的走线方式；
斜线一律跳过。`<path>` 也只解析绝对指令 M/H/V/L，含相对指令的一律放弃解析
（本项目不产生这种写法）。避开误报的做法见 `_crosses()` 的注释。

④ **只把"有填充的 rect"当方框**。虚线边界框（`fill:none`，表示"这一圈之内是顶层内部"）
不是障碍物，连线本来就该穿过它，否则外部信号进不来。
判据同样是从样式表解析出的 **fill 值**，不是类名白名单——见 `_fill_of()`。

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

SHAPES = {"rect", "path", "circle", "ellipse", "polygon", "polyline"}


def local(tag):
    """去掉 XML 命名空间，只留标签名"""
    return tag.split("}")[-1]


def extract_svgs(text):
    """从 HTML 或纯 SVG 文本里取出所有 <svg>…</svg> 块"""
    return re.findall(r"<svg\b.*?</svg>", text, re.S)


def parse_css_classes(text):
    """
    解析 <style> 块，返回 {类名: {属性名: 属性值}}

    只取"主体选择器"（逗号分组的最后一段复合选择器）里的类名：
    `.canvas svg` 的宽度是加在 svg 上的，不能算到 .canvas 头上。
    """
    props = {}
    for block in re.findall(r"<style[^>]*>(.*?)</style>", text, re.S):
        block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)   # 去 CSS 注释
        for sel_group, body in re.findall(r"([^{}]+)\{([^{}]*)\}", block):
            declared = {}
            for decl in body.split(";"):
                if ":" in decl:
                    k, v = decl.split(":", 1)
                    declared[k.strip().lower()] = v.strip()
            if not declared:
                continue
            for sel in sel_group.split(","):
                parts = re.split(r"[\s>+~]+", sel.strip())
                subject = parts[-1] if parts else ""
                for name in re.findall(r"\.([A-Za-z_][\w-]*)", subject):
                    props.setdefault(name, {}).update(declared)
    return props


def _fill_of(el, css):
    """
    元素最终生效的 fill 值（小写），解析不出来返回 None。
    优先级：行内 style > CSS 类 > fill= 表现属性。
    """
    v = el.attrib.get("fill")
    v = v.strip().lower() if v is not None else None
    for c in el.get("class", "").split():
        if "fill" in css.get(c, {}):
            v = css[c]["fill"].strip().lower()
    for decl in el.get("style", "").split(";"):
        if ":" in decl:
            k, val = decl.split(":", 1)
            if k.strip().lower() == "fill":
                v = val.strip().lower()
    return v


def _segments(el):
    """把 <line> 与轴对齐的 <path> 拆成线段列表 [(x1,y1,x2,y2), ...]"""
    tag, a = local(el.tag), el.attrib
    segs = []
    if tag == "line":
        try:
            segs.append((float(a["x1"]), float(a["y1"]),
                         float(a["x2"]), float(a["y2"])))
        except (KeyError, ValueError):
            pass
    elif tag == "path":
        d = a.get("d", "")
        if re.search(r"[a-z]", d):       # 含相对指令 → 不解析
            return []
        cur = None
        for cmd, argstr in re.findall(r"([MHVL])\s*([-\d.,\s]*)", d):
            nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", argstr)]
            if cmd in "HV":              # 单坐标命令：另一坐标沿用当前点
                for n in nums:
                    if cur is None:
                        break
                    nxt = (n, cur[1]) if cmd == "H" else (cur[0], n)
                    segs.append((cur[0], cur[1], nxt[0], nxt[1]))
                    cur = nxt
            else:                        # M / L：成对坐标
                for i in range(0, len(nums) - 1, 2):
                    nxt = (nums[i], nums[i + 1])
                    if cmd == "L" and cur is not None:
                        segs.append((cur[0], cur[1], nxt[0], nxt[1]))
                    cur = nxt
    return segs


def _crosses(seg, rect, eps=1.0):
    """
    线段是否穿过矩形**内部**。

    内缩 eps 再判定，是为了不把"贴着框边走"和"箭头落在框边上"算成穿框——
    那两种是正常画法，箭头的终点本来就该落在方框边界上。
    只判定轴对齐线段；斜线返回 False。
    """
    x1, y1, x2, y2 = seg
    rx, ry, rw, rh = rect
    l, t, r, b = rx + eps, ry + eps, rx + rw - eps, ry + rh - eps
    if l >= r or t >= b:
        return False
    if abs(x1 - x2) < 1e-6:                       # 竖线
        if not (l < x1 < r):
            return False
        lo, hi = sorted((y1, y2))
        return lo < b - eps and hi > t + eps
    if abs(y1 - y2) < 1e-6:                       # 横线
        if not (t < y1 < b):
            return False
        lo, hi = sorted((x1, x2))
        return lo < r - eps and hi > l + eps
    return False


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

    css = parse_css_classes(text)
    stats = {"svg": len(svgs), "shapes": 0, "colored_ok": 0, "classes": len(css)}

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

            # 该元素最终被声明了哪些属性：CSS 类 + 行内 style
            declared = set()
            for c in cls:
                declared |= set(css.get(c, {}))
            declared |= {d.split(":", 1)[0].strip().lower()
                         for d in style.split(";") if ":" in d}

            if "fill" in declared or "fill" in a:
                stats["colored_ok"] += 1
            else:
                problems.append(
                    f"SVG #{i} 的 <{local(el.tag)}> 没有显式填充"
                    f"（class={a.get('class', '—')}）→ 会渲染成黑色实心块"
                )

            # presentation attribute 会被同名 CSS 类属性压掉（行内 style 不算）
            for prop in ("stroke", "fill"):
                if prop in a and prop in declared:
                    problems.append(
                        f"SVG #{i} 的 <{local(el.tag)} class=\"{' '.join(cls)}\"> "
                        f"用了 `{prop}=\"{a[prop]}\"` 属性 —— "
                        f"类规则里有同名属性时会覆盖它（特异性为 0）。"
                        f"改用 style=\"{prop}:{a[prop]}\""
                    )

    # ---------- ④ 走线是否横穿方框 ----------
    # 只有"有填充的 rect"算方框：图例小色块太小不参与（MIN_W/MIN_H），
    # 虚线边界框 fill:none 是"区域"不是"障碍"，连线穿过它本来就是对的。
    MIN_W, MIN_H = 50.0, 30.0
    for i, sv in enumerate(svgs, 1):
        try:
            root = ET.fromstring(sv)
        except ET.ParseError:
            continue

        boxes = []
        for el in root.iter():
            if local(el.tag) != "rect":
                continue
            try:
                x, y = float(el.get("x", 0)), float(el.get("y", 0))
                w, h = float(el.get("width")), float(el.get("height"))
            except (TypeError, ValueError):
                continue
            if w < MIN_W or h < MIN_H:
                continue
            fill = _fill_of(el, css)
            if fill == "none" or fill == "transparent":
                continue                 # 边界/区域框，允许被穿过
            boxes.append((x, y, w, h, el.get("class", "—")))

        for el in root.iter():
            if local(el.tag) not in ("line", "path"):
                continue
            for s in _segments(el):
                for bx, by, bw, bh, bcls in boxes:
                    if _crosses(s, (bx, by, bw, bh)):
                        problems.append(
                            f"SVG #{i} 的 <{local(el.tag)} class=\"{el.get('class','—')}\"> "
                            f"线段 ({s[0]:g},{s[1]:g})→({s[2]:g},{s[3]:g}) "
                            f"横穿方框 [{bcls}] ({bx:g},{by:g} {bw:g}×{bh:g}) —— "
                            f"连线必须绕开方框"
                        )
                        break

    # ---------- 箭头 marker 引用是否存在 ----------
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
            print(f"    内嵌 SVG {stats['svg']} 张，绘制形状 {stats['shapes']} 个，"
                  f"样式表里解析到 {stats['classes']} 个类")
            if stats["classes"] == 0 and stats["shapes"]:
                print("    ⚠ 一个类都没解析到 —— 若文件确实用了 class，"
                      "说明 <style> 的解析方式要跟着改")
        if problems:
            total += len(problems)
            for p in problems:
                print(f"    ✗ {p}")
        else:
            print("    ✓ XML 合法 · 填充完整 · 无属性覆盖 · id 无冲突")

    print(f"\n{'=' * 52}")
    if total:
        print(f"共 {total} 个问题，详见 ERRORS.md ERR-0004 / ERR-0005")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

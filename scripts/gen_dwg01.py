# -*- coding: utf-8 -*-
"""gen_dwg01.py —— 生成《DWG-01 系统总体框图（第一层·7 个功能子系统）》的"含信号传递关系"版

【为什么要这个脚本，而不是手画一张图】
    老师要求总体框图**标明模块功能及模块间主要信号的传递关系**。
    信号名一旦手抄进图里，就成了 `docs/01` §2.1 连线表的**第二份拷贝** ——
    改接口时必然漏改其中一处（本项目 ERR-0014 的判据：同一事实的第二份拷贝＝下次改版必错的点）。
    所以本脚本把"框"和"线"都写成**数据结构**，与 §2.1 的连线表逐条对应；
    改接口时改 §2.1、改这里，再**重跑本脚本**，图与表就不会漂移。

【输出】（都写到 report/图/）
    · DWG-01-信号传递关系.svg   —— 矢量源，**可直接导入 draw.io 编辑**（每个框/箭头都是独立对象）
    · DWG-01-信号传递关系.png   —— 用无头 Chrome 渲染出来的成品图（插图/直接交作业用）

【用法】
    python scripts/gen_dwg01.py               # 生成 svg
    python scripts/gen_dwg01.py --png         # 生成 svg 并用 Chrome 无头渲染 png
    ⚠️ 改完必须**看着渲染出来的 PNG 逐段检查**（`CLAUDE.md` §12.4 第 3 步）：
       标签压线、压框在缩略图上看不出来。

【与其它文件的关系】
    · 信号名 = `docs/01-系统设计.md` §2.1 的连线表（唯一真值源）；
    · 模块功能 = `docs/01` §3.1 模块清单的"一句话职责"；
    · 本图是**对外提交版**（老师要的"模块功能＋信号传递关系"）；
      `docs/图/系统图.html` 的 DWG-01 是**内部对账版**（同一批框，不标信号名）。
      两者的事实来源同一个，改接口时两处都要改。
"""

import pathlib
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_SVG = ROOT / "report" / "图" / "DWG-01-信号传递关系.svg"
OUT_PNG = ROOT / "report" / "图" / "DWG-01-信号传递关系.png"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

W, H = 1400, 860
FONT = "Microsoft YaHei, SimHei, sans-serif"

# 配色（浅色主题；每个元素都写显式填充，便于 draw.io 导入后仍是这个样子）
C = dict(
    canvas="#ffffff",
    cont_fill="#f6f7f9", cont_stroke="#c8ccd4",
    box_stroke="#3c4043", text="#202124", sub="#5f6368",
    data="#3c4043", tick="#e08600", rst="#1a73e8", fb="#c5221f", dev="#5f6368",
)

# ============================================================
# 框： (x, y, w, h, 标题, 实体行, 功能行, 填色, 描边色)
#   位置按"数据通路从左到右、随机数据在下方、音效在右下"布版
# ============================================================
B = [
    # 外部器件（图外）
    dict(id="sw7",  x=30,  y=100, w=140, h=32, head="SW7 系统开关", ent="", func="", f="#ffffff", s=C["dev"]),
    dict(id="btn",  x=30,  y=142, w=140, h=32, head="BTN0 复位键", ent="", func="", f="#ffffff", s=C["dev"]),
    dict(id="kbd",  x=30,  y=300, w=120, h=80, head="4×4 矩阵键盘", ent="KEY1~KEY16", func="按下=1·ROW3 最上排", f="#ffffff", s=C["dev"]),
    dict(id="dsp",  x=1260, y=290, w=130, h=80, head="数码管（8 位）", ent="DISP7 → DISP0", func="", f="#ffffff", s=C["dev"]),
    dict(id="mtx",  x=1260, y=395, w=130, h=80, head="8×8 双色点阵", ent="行低有效 / 列高有效", func="", f="#ffffff", s=C["dev"]),
    dict(id="buz",  x=1260, y=660, w=130, h=56, head="蜂鸣器", ent="无源 · 频率可控", func="", f="#ffffff", s=C["dev"]),
    # 7 个功能子系统（DWG-01 的框）
    dict(id="s1", x=525, y=88, w=190, h=72, head="时钟与节拍  S1", ent="clk_gen",
         func="50MHz → 5 档节拍 + 复位", f="#ffe6e6", s="#d93025"),
    dict(id="s2", x=230, y=305, w=150, h=100, head="键盘输入  S2", ent="keypad_scan",
         func="4×4 扫描 · 80ms 消抖", f="#e8f0fe", s="#4285f4"),
    dict(id="s3", x=470, y=305, w=150, h=100, head="游戏控制  S3", ent="game_fsm",
         func="状态机 · 倒计时 · 关卡", f="#fff4e5", s="#f29900"),
    dict(id="s4", x=750, y=305, w=150, h=100, head="拼图核心  S4", ent="puzzle_ctrl",
         func="锚点 · 钳位 · 锁定 · 判定", f="#e6f4ea", s="#188038"),
    dict(id="s6", x=1030, y=305, w=150, h=100, head="显示子系统  S6", ent="disp_format · seg_scan",
         func="dot_matrix_scan（两路扫描）", f="#f3e8fd", s="#8430ce", ent_sz=8.5, func_sz=8.5),
    dict(id="s5", x=470, y=500, w=150, h=100, head="图案与随机数据  S5", ent="pattern_rom · piece_rom",
         func="rng_lfsr · 图案 / 零片 / 随机数", f="#e6f4ea", s="#188038", ent_sz=8.5, func_sz=8.5),
    dict(id="s7", x=1030, y=630, w=150, h=100, head="音效输出  S7", ent="buzzer_ctrl",
         func="8 种音效 · 方波合成", f="#f3e8fd", s="#8430ce"),
]

# ============================================================
# 连线： (折点列表, 线型, 标签行, 标签位置, 锚点, 箭头端)
#   线型： data 数据/控制（实线）· tick 节拍（橙虚线）· rst 复位（蓝虚线）· fb 状态级反馈（红虚线）
#   ⚠️ 每条线的标签都对应 `docs/01` §2.1 连线表里的某一条（注释里标了条号）
# ============================================================
E = [
    # ---- 系统级（外部 → 系统）----
    dict(pts=[(170, 116), (525, 116)], k="data", lb=["sw7（另 → 顶层输出级门控）"], xy=(345, 104)),
    dict(pts=[(170, 158), (525, 158)], k="data", lb=["btn"], xy=(345, 148)),

    # ---- 13 条：键盘输入 → 矩阵键盘（列扫描）／D 条 kp_row ----
    dict(pts=[(150, 330), (230, 330)], k="data", lb=["kp_row[3:0]"], xy=(190, 320)),
    dict(pts=[(230, 372), (150, 372)], k="data", lb=["kp_col[3:0]"], xy=(190, 394)),

    # ---- 节拍与复位总线（第 0 条）----
    dict(pts=[(620, 160), (620, 250), (1105, 250)], k="tick", lb=[], xy=(0, 0), a="none"),
    dict(pts=[(265, 250), (265, 305)], k="tick", lb=[], xy=(0, 0), a="end"),
    dict(pts=[(545, 250), (545, 305)], k="tick", lb=[], xy=(0, 0), a="end"),
    dict(pts=[(1105, 250), (1105, 305)], k="tick", lb=[], xy=(0, 0), a="end"),
    dict(pts=[(960, 250), (960, 640), (1030, 640)], k="tick", lb=["tick_8k"], xy=(880, 628)),
    dict(pts=[(660, 160), (660, 272), (1105, 272)], k="rst", lb=[], xy=(0, 0), a="none"),
    dict(pts=[(265, 272), (265, 305)], k="rst", lb=[], xy=(0, 0), a="end"),
    dict(pts=[(545, 272), (545, 305)], k="rst", lb=[], xy=(0, 0), a="end"),
    dict(pts=[(825, 272), (825, 305)], k="rst", lb=[], xy=(0, 0), a="end"),
    dict(pts=[(1105, 272), (1105, 305)], k="rst", lb=[], xy=(0, 0), a="end"),
    dict(pts=[(410, 272), (410, 550), (470, 550)], k="rst", lb=["rst"], xy=(384, 540)),
    dict(pts=[(980, 272), (980, 672), (1030, 672)], k="rst", lb=["rst"], xy=(905, 660)),

    # ---- 1 条：键盘输入 → 游戏控制 ----
    dict(pts=[(380, 345), (470, 345)], k="data",
         lb=["key_code[4:0]", "key_press"], xy=(425, 322)),
    # ---- 2 条：游戏控制 → 拼图核心（转发操作键脉冲）----
    dict(pts=[(620, 345), (750, 345)], k="data",
         lb=["round_start · sel · conf", "dir[3:0]（含连发）"], xy=(685, 322)),
    # ---- 3 条：游戏控制 → 图案与随机数据 ----
    dict(pts=[(505, 405), (505, 500)], k="data",
         lb=["pattern_sel[2:0] · seed[7:0]", "seed_load"], xy=(452, 430), anchor="end"),
    # ---- 4 条：拼图核心 → 图案与随机数据（请求推进 LFSR）----
    dict(pts=[(770, 405), (770, 435), (600, 435), (600, 500)], k="fb",
         lb=["rnd_step"], xy=(716, 424)),
    # ---- 5 条：图案与随机数据 → 拼图核心 ----
    dict(pts=[(560, 500), (560, 470), (860, 470), (860, 405)], k="data",
         lb=["target_mask[63:0] · rel_mask[3×64]", "height · width · count[2:0] · rnd[7:0]"],
         xy=(742, 480)),
    # ---- 6 条：拼图核心 → 显示子系统（零片像素）----
    dict(pts=[(900, 345), (1030, 345)], k="data",
         lb=["px_red[63:0]", "px_green[63:0]"], xy=(965, 322)),
    # ---- 7 条：游戏控制 → 显示子系统（状态/关卡/倒计时/闪烁）----
    #      ⚠️ 必须走 S5 左侧的空走廊（x=440）：走 x=560~620 会**穿过 S5 方框**
    dict(pts=[(470, 385), (440, 385), (440, 690), (1005, 690), (1005, 375), (1030, 375)], k="data",
         lb=["state[2:0] · level · preview_cnt[2:0]", "game_cnt_bcd[7:0] · blink"],
         xy=(830, 662)),
    # ---- 8 条：游戏控制 → 音效输出 ----
    #      同理走 S5 左侧走廊（x=420），从音效输出框的下方进入
    dict(pts=[(470, 365), (420, 365), (420, 750), (1105, 750), (1105, 730)], k="data",
         lb=["sound_sel[2:0] · sound_trig"], xy=(840, 764)),
    # ---- 9 条：拼图核心 → 游戏控制（唯一的状态级反馈）----
    dict(pts=[(755, 405), (755, 425), (580, 425), (580, 405)], k="fb",
         lb=["all_locked · solved"], xy=(672, 414)),
    # ---- 10 条：显示子系统 → 器件 ----
    dict(pts=[(1180, 330), (1260, 330)], k="data", lb=["seg[7:0]", "cat[7:0]"], xy=(1220, 306)),
    dict(pts=[(1180, 442), (1260, 442)], k="data",
         lb=["dot_row[7:0]", "dot_colr[7:0]", "dot_colg[7:0]"], xy=(1220, 404)),
    # ---- 11 条：音效输出 → 蜂鸣器 ----
    dict(pts=[(1180, 686), (1260, 686)], k="data", lb=["buzz"], xy=(1220, 674)),
    # ---- 12 条：图案与随机数据 → 显示子系统（预览/胜负图案）----
    dict(pts=[(620, 570), (960, 570), (960, 415), (1050, 415), (1050, 405)], k="data",
         lb=["pattern_mask[63:0]"], xy=(790, 558)),
]

# 端口名标注：不在这里另写一份（会与 E 表里的连线标签变成同一信号的第二份拷贝），
# 键盘那一对方向相反的器件线标签就写在 E 表里（kp_row 向右 / kp_col 向左）。
PORTS = []


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def txt(x, y, s, size=11, anchor="middle", fill=None, bold=False, italic=False, halo=True):
    fill = fill or C["text"]
    extra = ""
    if halo:
        extra = ' paint-order="stroke" stroke="#ffffff" stroke-width="3.2" stroke-linejoin="round"'
    return (f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" '
            f'text-anchor="{anchor}" fill="{fill}"'
            f'{" font-weight=\"bold\"" if bold else ""}'
            f'{" font-style=\"italic\"" if italic else ""}{extra}>{esc(s)}</text>')


def box(b):
    x, y, w, h = b["x"], b["y"], b["w"], b["h"]
    s = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" ry="8" '
         f'fill="{b["f"]}" stroke="{b["s"]}" stroke-width="1.6"/>']
    lines = [b["head"]] + ([b["ent"]] if b["ent"] else []) + ([b["func"]] if b["func"] else [])
    if not b["head"]:
        return ""
    n = len(lines)
    # 标题自适应字号（长标题自动缩到 11.5，避免压框）；其余 9.5px；整块文字垂直居中
    head_sz = 13 if len(b["head"]) <= 10 else 11.5
    lh = [17] + [13] * (n - 1)
    total = sum(lh)
    cy = y + h / 2 - total / 2 + 12
    for i, ln in enumerate(lines):
        sz = head_sz if i == 0 else (b.get("ent_sz", 9.5) if i == 1 else b.get("func_sz", 9.5))
        s.append(txt(x + w / 2, cy, ln, size=sz, bold=(i == 0),
                     fill=C["text"] if i == 0 else C["sub"]))
        cy += lh[i]
    return "".join(s)


def edge(e):
    pts = e["pts"]
    d = " ".join(("M" if i == 0 else "L") + f"{p[0]},{p[1]}" for i, p in enumerate(pts))
    dash = {"tick": ' stroke-dasharray="7,4"', "rst": ' stroke-dasharray="2,3"',
            "fb": ' stroke-dasharray="6,4"'}.get(e["k"], "")
    col = {"tick": C["tick"], "rst": C["rst"], "fb": C["fb"]}.get(e["k"], C["data"])
    wd = {"tick": 1.8, "rst": 1.6, "fb": 1.8}.get(e["k"], 1.6)
    s = [f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{wd}"{dash} '
         f'stroke-linejoin="round"/>']
    # 箭头：箭头尖在终点、**箭身朝来的方向伸**（这样箭头不会画进方框内部）
    if e.get("a", "end") in ("end", "start"):
        (x1, y1), (x2, y2) = pts[-2], pts[-1]
        if e.get("a", "end") == "start":
            (x1, y1), (x2, y2) = pts[1], pts[0]
        if x1 < x2:                       # →  向右
            base = f"{x2 - 9},{y2 - 4.5} {x2 - 9},{y2 + 4.5}"
        elif x1 > x2:                     # ←  向左
            base = f"{x2 + 9},{y2 - 4.5} {x2 + 9},{y2 + 4.5}"
        elif y1 < y2:                     # ↓  向下
            base = f"{x2 - 4.5},{y2 - 9} {x2 + 4.5},{y2 - 9}"
        else:                             # ↑  向上
            base = f"{x2 - 4.5},{y2 + 9} {x2 + 4.5},{y2 + 9}"
        s.append(f'<path d="M{x2},{y2} L{base} Z" fill="{col}"/>')
    for i, ln in enumerate(e["lb"]):
        s.append(txt(e["xy"][0], e["xy"][1] + i * 12, ln, size=10.5, fill=col,
                     anchor=e.get("anchor", "middle")))
    return "".join(s)


def head():
    # ⚠️ 有意**不画整幅白底 <rect>**：`scripts/check_svg.py` 会把"有填充的矩形"当成障碍方框，
    #    一张铺满画布的底会被判成"所有走线都横穿方框"（79 条假报，ERR-0004/0007 同一类）。
    #    白底由浏览器/截图参数给（Chrome 用 --default-background-color=FFFFFFFF）。
    s = [txt(W / 2, 34, "图 DWG-01  系统总体框图（第一层 · 7 个功能子系统）"
                         "—— 含模块功能与模块间信号传递关系", size=17, bold=True)]
    s.append(txt(W / 2, 56, "题目 4《简易拼图游戏的设计与实现》 · 目标器件 Altera MAX II "
                            "EPM1270T144C5 · 设计语言 VHDL · 开发工具 Quartus II 9.1", size=10.5,
                 fill=C["sub"]))
    # 内部核心功能框图容器
    #   ⚠️ **fill="none" 是刻意的**：`scripts/check_svg.py` 只把"有填充的矩形"当障碍方框
    #      （ERR-0007 的判据），容器是"范围"不是"障碍"。给它填灰色会让图内 70 多条线
    #      全被判成"横穿方框"（同 ERR-0004 那类假报）。分组靠虚线框 + 左上标签表达。
    s.append(f'<rect x="165" y="215" width="1050" height="560" rx="12" ry="12" '
             f'fill="none" stroke="{C["cont_stroke"]}" stroke-width="1.4" '
             f'stroke-dasharray="6,4"/>')
    s.append(txt(178, 234, "内部核心功能框图（第一层：7 个功能子系统，框内注明所含实体与职责）",
                 size=10, anchor="start", fill=C["sub"]))
    return "".join(s)


def callout():
    """节拍与复位总线说明（把"哪根线送给谁"写成可数的事实，而不是画 6 条交叉线）"""
    x, y, w, h = 730, 88, 430, 104
    s = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" ry="8" '
         f'fill="#fffdf5" stroke="{C["tick"]}" stroke-width="1.2"/>']
    s.append(txt(x + 10, y + 18, "节拍与复位总线（时钟与节拍 S1 输出）", size=11, anchor="start",
                 bold=True, fill=C["tick"]))
    for i, ln in enumerate([
        "rst（同步高有效）→ S2 · S3 · S4 · S5 · S6 · S7 全部 6 个子系统",
        "tick_1k → 键盘输入     tick_8k → 显示子系统 · 音效输出",
        "tick_100 / tick_2hz / tick_1hz → 游戏控制",
        "S4 拼图核心 与 S5 图案与随机数据 不接任何节拍，只收 rst",
        "clk（50MHz）由顶层直连各时序实体，见 docs/01 §2.1 第 A 条",
    ]):
        s.append(txt(x + 10, y + 35 + i * 14, ln, size=9, anchor="start", fill=C["sub"]))
    return "".join(s)


def legend():
    x, y = 180, 806
    items = [("数据 / 控制（实线）", "data"), ("节拍使能（单周期，橙虚线）", "tick"),
             ("同步复位 rst（蓝点线）", "rst"), ("状态级反馈 / 请求（红虚线）", "fb")]
    s = []
    cx = x
    for name, k in items:
        col = {"tick": C["tick"], "rst": C["rst"], "fb": C["fb"]}.get(k, C["data"])
        dash = {"tick": ' stroke-dasharray="7,4"', "rst": ' stroke-dasharray="2,3"',
                "fb": ' stroke-dasharray="6,4"'}.get(k, "")
        s.append(f'<line x1="{cx}" y1="{y}" x2="{cx + 32}" y2="{y}" stroke="{col}" '
                 f'stroke-width="2"{dash}/>')
        s.append(txt(cx + 38, y + 4, name, size=10, anchor="start", fill=C["sub"]))
        cx += 38 + len(name) * 11
    # 注释单独一行，避免与图例挤在一起
    s.append(txt(180, y + 24,
                 "注：信号名与 docs/01 §2.1 连线表逐条一致（4 条系统级 + 14 条子系统出线 = 18 条）；"
                 "该表是接口的唯一真值源，改接口须同步改表与本图；"
                 "顶层输出级由 SW7 组合门控（SW7=0 时全部显示熄灭、蜂鸣器静音）。",
                 size=9.5, anchor="start", fill=C["sub"]))
    return "".join(s)


def build() -> str:
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
             f'width="{W}" height="{H}">', head()]
    # 先画线（在框下面），再画框，最后画标注
    parts += [edge(e) for e in E]
    parts += [box(b) for b in B]
    parts.append(callout())
    for name, x, y, a, col in PORTS:
        parts.append(txt(x, y, name, size=10, fill=col, anchor=a, italic=True))
    parts.append(legend())
    parts.append("</svg>")
    return "".join(parts)


def main() -> int:
    svg = build()
    OUT_SVG.parent.mkdir(parents=True, exist_ok=True)
    OUT_SVG.write_text(svg, encoding="utf-8")
    print(f"  ✓ {OUT_SVG.relative_to(ROOT)}  ({len(svg)} 字符)")

    if "--png" in sys.argv:
        cmd = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
               "--force-device-scale-factor=2",          # 2 倍分辨率：插图/打印都清晰
               f"--window-size={W},{H}", "--default-background-color=FFFFFFFF",
               f"--screenshot={OUT_PNG}", OUT_SVG.as_uri()]
        r = subprocess.run(cmd, capture_output=True)
        ok = OUT_PNG.exists() and OUT_PNG.stat().st_size > 5000
        print(f"  {'✓' if ok else '✗'} {OUT_PNG.relative_to(ROOT)}  "
              f"({OUT_PNG.stat().st_size if OUT_PNG.exists() else 0} bytes)")
        if not ok:
            print("    Chrome 输出：", r.stderr.decode("utf-8", "replace")[-500:])
    print("  ⚠️ 请打开 PNG 放大逐段检查标签是否压线/压框（CLAUDE.md §12.4 第 3 步）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

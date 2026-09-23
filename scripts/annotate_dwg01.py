# -*- coding: utf-8 -*-
"""annotate_dwg01.py —— 在**原白板图**上加"模块间信号名"小标注（不重画、不改原内容）

【为什么是"加标注"而不是"重画"】
    `report/图/DWG-01-白板排版-已按定稿口径修正.png`（3822×2088）是用户已认可的版式，
    老师只要求补上**模块间主要信号的传递关系**。所以这里**只叠加小字标注**：
    原图的框、线、中文说明一律不动，输出另存为新文件（原图保留）。

【标注内容与依据】
    · 信号名 = `docs/01-系统设计.md` §2.1 连线表（唯一真值源）；
    · 每条标注旁边都注明了它对应连线表的哪一条，改接口时两处一起改；
    · 只标"模块间主要信号"，不追求逐条穷举（老师原话：标明**主要**信号的传递关系）。

【位置怎么定】
    原图的框与连线位置是**量出来的**（见下表 LANDMARKS），不是估计：
    用纯 PIL 扫暗像素找长横/长竖线（`.tmp/detect_lines.py`），
    再用 1080 宽预览图与 3822 宽原图的缩放比 3.538 换算各框位。

【用法】
    python scripts/annotate_dwg01.py            # 生成带标注的 PNG
    python scripts/annotate_dwg01.py --show     # 顺便打印每条标注的坐标（微调时看）
"""

import pathlib
import sys
from PIL import Image, ImageDraw, ImageFont

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "report" / "图" / "DWG-01-白板排版-已按定稿口径修正.png"
DST = ROOT / "report" / "图" / "DWG-01-白板版-含信号传递关系.png"

FONT_ASCII = r"C:\Windows\Fonts\consola.ttf"     # 信号名（等宽，像代码）
FONT_CN = r"C:\Windows\Fonts\msyh.ttc"           # 中文
SZ = 34          # 信号名字号（原图 3822 宽，34px ≈ 报告插图里 3.6mm 高，清晰可读）
SZ_S = 30        # 中文小注

COL_DATA = (60, 64, 67)      # 数据/控制：深灰（与图上的黑线一致）
COL_TICK = (214, 130, 0)     # 节拍：橙（与图上的橙虚线一致）
COL_CN = (90, 90, 95)        # 中文小注：灰

# (锚点x, 锚点y, 文字, 字体, 颜色, 对齐)  对齐：mm 居中 / lm 左中 / rm 右中
L = [
    # ---- 系统级：外部输入 ----
    (1120, 252, "sw7",                       FONT_ASCII, COL_DATA, "mm"),   # 表① B 条
    (1120, 352, "btn",                       FONT_ASCII, COL_DATA, "mm"),   # 表① C 条
    (418,  902, "[3:0] 按下=1",               FONT_CN,    COL_DATA, "lm"),   # 表① D 条
    (418, 1002, "[3:0] 扫描输出",             FONT_CN,    COL_DATA, "lm"),   # 表② 13 条

    # ---- 子系统出线（连线表编号）----
    (1142, 878, "key_code[4:0]",             FONT_ASCII, COL_DATA, "mm"),   # 1 条
    (1142, 916, "key_press",                 FONT_ASCII, COL_DATA, "mm"),
    (1832, 872, "round_start · sel",         FONT_ASCII, COL_DATA, "mm"),   # 2 条
    (1832, 908, "conf · dir[3:0]",           FONT_ASCII, COL_DATA, "mm"),
    (1832, 806, "all_locked · solved",       FONT_ASCII, COL_DATA, "mm"),   # 9 条（状态级反馈）
    (1462, 1240, "pattern_sel · seed",       FONT_ASCII, COL_DATA, "rm"),   # 3 条
    (1462, 1276, "seed_load",                FONT_ASCII, COL_DATA, "rm"),
    (1556, 1240, "state · level",            FONT_ASCII, COL_DATA, "lm"),   # 7 条
    (1556, 1276, "game_cnt_bcd · blink",     FONT_ASCII, COL_DATA, "lm"),
    (1566, 1560, "sound_sel · sound_trig",   FONT_ASCII, COL_DATA, "lm"),   # 8 条
    (2172, 1234, "rnd_step",                 FONT_ASCII, COL_DATA, "lm"),   # 4 条
    (2172, 1290, "target_mask[63:0]",        FONT_ASCII, COL_DATA, "lm"),   # 5 条
    (2172, 1326, "rel_mask · height · width", FONT_ASCII, COL_DATA, "lm"),
    (2450, 1140, "px_red[63:0] · px_green[63:0]", FONT_ASCII, COL_DATA, "mm"),  # 6 条
    (2790, 1290, "pattern_mask[63:0]",       FONT_ASCII, COL_DATA, "mm"),   # 12 条
    (3140, 900,  "seg[7:0] · cat[7:0]",      FONT_ASCII, COL_DATA, "lm"),   # 10 条
    (3140, 1096, "dot_row · dot_colr · dot_colg", FONT_ASCII, COL_DATA, "lm"),
    (3140, 1990, "buzz",                     FONT_ASCII, COL_DATA, "lm"),   # 11 条

    # ---- 节拍与复位（第 0 条）----
    (2200, 560, "rst + tick_8k / 1k / 100 / 2hz / 1hz", FONT_ASCII, COL_TICK, "lm"),
    (2860, 700, "tick_8k",                   FONT_ASCII, COL_TICK, "mm"),
    (800,  700, "tick_1k",                   FONT_ASCII, COL_TICK, "mm"),
    (2760, 800, "rst",                       FONT_ASCII, COL_TICK, "mm"),
]


def main() -> int:
    im = Image.open(SRC).convert("RGB")
    d = ImageDraw.Draw(im)
    for x, y, s, fpath, col, align in L:
        try:
            f = ImageFont.truetype(fpath, SZ if fpath == FONT_ASCII else SZ_S)
        except OSError:
            f = ImageFont.load_default()
        anchor = {"mm": "mm", "lm": "lm", "rm": "rm"}[align]
        # 白描边（halo）：压在线/框上也看得清，且不用盖住原图任何内容
        d.text((x, y), s, font=f, fill=col, anchor=anchor,
               stroke_width=7, stroke_fill=(255, 255, 255))
        if "--show" in sys.argv:
            print(f"  ({x:>4},{y:>4}) {align}  {s}")
    DST.parent.mkdir(parents=True, exist_ok=True)
    im.save(DST)
    print(f"  ✓ {DST.relative_to(ROOT)}  {im.size[0]}×{im.size[1]}  共 {len(L)} 条标注")
    print("  ⚠️ 请打开 PNG 放大检查：字要贴着对应的线、不压住原图文字")
    return 0


if __name__ == "__main__":
    sys.exit(main())

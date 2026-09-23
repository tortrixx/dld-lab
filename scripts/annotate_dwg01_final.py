# -*- coding: utf-8 -*-
"""annotate_dwg01_final.py —— 在**用户定稿版**白板图上补 4 处信号名标注

【背景】
    `report/图/DWG-01-系统总体框图-含信号传递关系-定稿版.png` 是**用户自己在白板里画的**，
    版式已定稿。按 `docs/01` §2.1 连线表逐条核对后，还差 4 条**主要信号**没标：
      ① 键盘输入 → 游戏控制     缺 `key_code[4:0]`（现在只有 key_press）
      ② 游戏控制 → 拼图核心     缺 `sel · conf · dir[3:0]`（现在只有 round_start）
      ③ 拼图核心 → 游戏控制     缺 `all_locked · solved`（反馈线现在只有中文说明）
      ④ 游戏控制 → 音效输出     整条线没标，缺 `sound_sel · sound_trig`
    本脚本只**叠加这 4 处小字**（白描边、带白底），原图内容一个字不动。

【位置怎么定】
    与 `annotate_dwg01.py` 同一套办法：先扫暗像素找长横/长竖线把坐标量出来
    （本图标定值见下面 LIN 注释），再据此放置。微调只改 L 表里的 (x, y)。

【用法】
    python scripts/annotate_dwg01_final.py            # 就地更新定稿版 PNG（原导出在 git 历史里）
    python scripts/annotate_dwg01_final.py --backup   # 先把当前图另存为 ……原始导出.png 再改
"""

import pathlib
import shutil
import sys
from PIL import Image, ImageDraw, ImageFont

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIG = ROOT / "report" / "图" / "DWG-01-系统总体框图-含信号传递关系-定稿版.png"
BAK = ROOT / "report" / "图" / "DWG-01-系统总体框图-定稿版-白板原始导出.png"

FONT = r"C:\Windows\Fonts\consola.ttf"
SZ = 28                       # 与用户原图里的信号名字号接近（原图 4034 宽）
COL = (60, 64, 67)            # 深灰，与用户原图信号名同色

# 本图**实测**标定值（2026-09-23，按填充色/暗像素扫出来的，不是估的）：
#   数据通路行的四个框（y 828..1042，中线 y=935）：
#     键盘输入 x 645..1021 ｜ 游戏控制 x 1311..1700 ｜ 拼图核心 x 1991..2430 ｜ 显示子系统 x 2630..3069
#   图案与随机数据 x 1992..2424, y 1484..1698 ｜ 音效输出 x 2786..3144, y 1782..1970 ｜ 时钟中心 (1870,262)
#   节拍总线 y≈583 ｜ rst 分支 y≈807 ｜ 反馈虚线+中文说明 y≈760（x 1350..1938）
#   游戏控制→音效输出：竖 x≈1600、横 y≈1878（到 x 2774）
#   ⇒ 因此把标注放在"两框之间的空档"或"线段的空侧"：
L = [
    (1166, 895, "key_code[4:0]"),              # ① 键盘输入→游戏控制 空档 x1021..1311 的上方
    (1845, 985, "sel · conf"),                 # ② 游戏控制→拼图核心 空档 x1700..1991，放到箭头下方
    (1845, 1017, "dir[3:0]"),                  #    （上方被"反馈游戏是否结束"占着）
    (1560, 700, "all_locked"),                 # ③ 反馈线：贴在中文说明左侧的空位
    (1560, 732, "· solved"),
    (2150, 1845, "sound_sel · sound_trig"),    # ④ 游戏控制→音效输出 那条横线（y≈1878）上方
]


def main() -> int:
    if "--backup" in sys.argv and not BAK.exists():
        shutil.copy2(FIG, BAK)
        print(f"  ✓ 已另存原始导出：{BAK.name}")

    im = Image.open(FIG).convert("RGB")      # 顺带压成 RGB（白底），插 Word/PDF 更稳
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(FONT, SZ)
    for x, y, s in L:
        d.text((x, y), s, font=f, fill=COL, anchor="mm",
               stroke_width=6, stroke_fill=(255, 255, 255))
    im.save(FIG)
    print(f"  ✓ {FIG.name}  已补 {len(L)} 行标注（{im.size[0]}×{im.size[1]}，RGB）")
    print("  ⚠️ 请打开 PNG 放大检查：字要贴着对应的线、不压住原有内容")
    return 0


if __name__ == "__main__":
    sys.exit(main())

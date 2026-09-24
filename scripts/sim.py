#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sim.py —— 模块级功能仿真驱动（Quartus II 9.1 内置仿真器）

【为什么需要它】
    本机没有 ModelSim / GHDL，只能用 Quartus II 9.1 内置仿真器。它的三条硬限制
    （`CLAUDE.md` §5.3 实测确认）：仿的是**综合后网表**（不支持 testbench/assert）、
    **没有任何 Tcl 接口**（`::quartus::simulator` 是空包）、**必须有一个 .vwf 向量源**。
    所以驱动与判定只能全用 Python —— 本脚本就是那条链路的第 2/4 步。

【标准循环】（`docs/03-仿真验证方案.md` §2，一步不能省）
    写 sim/tb_<模块>.py  →  Python 生成 .vwf  →  跑 quartus_sim
    →  Python 解析回写结果 + 与参考模型逐点比对  →  渲染波形图存 docs/图/
    →  把原始数据写进 docs/03  →  单独 commit

【用法】
    python scripts/sim.py gen   <模块>    # 只生成激励 .vwf（不碰工程）
    python scripts/sim.py check <模块>    # 只解析结果 + 比对 + 出图
    python scripts/sim.py run   <模块>    # 一键：绑定 → 生成网表 → 仿真 → 比对 → 还原

【两个"绑定"步骤 —— 必须做，且必须用完还原】（`docs/03` §2.1）
    工程只有一个顶层、一个向量源设置。要仿到被测模块，中间必须改两次工程设置：
      A. TOP_LEVEL_ENTITY  → 被测模块（否则被测模块根本不在网表顶层，加不进波形）
      B. VECTOR_SOURCE_FILE → sim/<模块>.vwf（否则报 `No valid vector source file specified`）
    ⚠️ 两者都会在关工程时**写回 .qsf**。本脚本用"整文件备份 / 还原"来保证
       **跑完之后 .qsf 与跑之前逐字节相同**（比逐项还原更稳，见 `build.tcl` 的教训）。

【tb 模块契约】
    sim/tb_<模块>.py 必须提供两个函数：
        build(b)   —— b 是 vwf.Builder，在里面声明节点 + 驱动激励
        check(vf)  —— vf 是解析后的 vwf.VwfFile，返回 [(名称, 是否通过, 说明), ...]
"""

import importlib.util
import pathlib
import re
import shutil
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
QUARTUS_BIN = pathlib.Path(r"C:\QuartusII91\QuartusII91\quartus\bin")
PROJ_NAME = "puzzle"
PROJ_DIR = ROOT / "quartus"
QSF = PROJ_DIR / (PROJ_NAME + ".qsf")
SIM_DIR = ROOT / "sim"
FIG_DIR = ROOT / "docs" / "图"

sys.path.insert(0, str(ROOT / "scripts"))
import vwf  # noqa: E402  （同目录的 .vwf 读写库）


# ============================================================
# tb 装载
# ============================================================
def tb_path(module: str) -> pathlib.Path:
    return SIM_DIR / ("tb_%s.py" % module)


def load_tb(module: str):
    p = tb_path(module)
    if not p.exists():
        raise SystemExit("✗ 找不到 %s —— 每个模块都要有自己的激励与断言文件" % p)
    spec = importlib.util.spec_from_file_location("tb_" + module, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for fn in ("build", "check"):
        if not hasattr(mod, fn):
            raise SystemExit("✗ %s 缺少 %s() 函数（契约见 sim.py 头部）" % (p, fn))
    return mod


def vwf_path(module: str) -> pathlib.Path:
    return SIM_DIR / (module + ".vwf")


# ============================================================
# 第 2 步：生成激励
# ============================================================
def cmd_gen(module: str) -> int:
    tb = load_tb(module)
    b = vwf.Builder(duration=tb.DURATION, grid_period=tb.GRID_PERIOD)
    tb.build(b)
    out = vwf_path(module)
    b.write(str(out))
    print("  ✓ 已生成激励 %s（时长 %.1f %s）" % (out, tb.DURATION, vwf.TIME_UNIT))
    print("  ⚠️ 该文件会被仿真结果覆盖写回 —— 永远不要手工编辑，改 tb_*.py 重新生成。")
    return 0


# ============================================================
# 第 4 步：解析 + 比对 + 出图
# ============================================================
def _has_wave(vf, name: str) -> bool:
    """该节点在回写的 .vwf 里有没有波形。
    ⚠️ 总线本身**不会有** TRANSITION_LIST（`Builder.write` 对总线 continue），
       要落到它的各比特上查 —— 这是 docs/03 §3.1 第 5 条的落地点。"""
    if name in vf.transitions:
        return True
    sig = vf.signals.get(name)
    if sig is not None and sig.is_bus:
        return any(("%s[%d]" % (name, b)) in vf.transitions for b in range(sig.width))
    return False


def _bus_trace(vf, name: str):
    """总线的 [(时刻, 整数值或 'X')]，由各比特的变化时刻合成（供出图用）。"""
    sig = vf.signals.get(name)
    if sig is None or not sig.is_bus:
        return vf.trace(name)
    times = set()
    for b in range(sig.width):
        for (t, _lv) in vf.trace("%s[%d]" % (name, b)):
            times.add(t)
    out = []
    for t in sorted(times):
        v = vf.bus_value_at(name, t + 1e-9)
        if v is None:
            v = "X"
        if not out or out[-1][1] != v:
            out.append((t, v))
    return out


def cmd_check(module: str) -> int:
    tb = load_tb(module)
    p = vwf_path(module)
    if not p.exists():
        raise SystemExit("✗ 找不到 %s —— 先跑 `sim.py gen %s` 并完成仿真" % (p, module))

    vf = vwf.parse(str(p))

    # ⚠️ docs/03 §3.1 第 5 条：中间信号清单缺一即报错。
    #    名字对不上时的表现**不是显眼报错，而是该节点干脆没有波形** —— 必须显式断言。
    missing = [n for n in getattr(tb, "OBSERVE", []) if not _has_wave(vf, n)]
    if missing:
        print("  ✗ 观测点缺失（该节点没有 TRANSITION_LIST，说明名字在综合后网表里不存在）：")
        for m in missing:
            print("      %s" % m)
        print("  → 改 sim/tb_%s.py 的 OBSERVE 清单，或换个功能上必须保留的等价观测点。" % module)
        return 1

    results = tb.check(vf)

    print()
    print("=" * 66)
    print(" %s —— 参考模型逐点比对" % module)
    print("=" * 66)
    n_pass = 0
    for name, ok, detail in results:
        print("  %s %s" % ("✓" if ok else "✗", name))
        if detail:
            for line in str(detail).split("\n"):
                print("      %s" % line)
        n_pass += 1 if ok else 0
    print("-" * 66)
    print("  合计：%d / %d 通过" % (n_pass, len(results)))
    print("=" * 66)

    svg = render_svg(vf, getattr(tb, "OBSERVE", []), module)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig = FIG_DIR / ("SIM-%s.svg" % module)
    fig.write_text(svg, encoding="utf-8")
    print("  ✓ 波形图已存 %s" % fig.relative_to(ROOT))

    return 0 if n_pass == len(results) else 1


# ============================================================
# 波形渲染（自写 SVG，本机没有 matplotlib）
# ============================================================
def _fmt_time(t: float) -> str:
    return ("%.0f" % t) if abs(t) >= 1 else ("%.1f" % t)


def render_svg(vf, names, title, max_sig: int = 24) -> str:
    """把若干信号的波形画成一张内联 SVG（数字波形，总线画十六进制）。"""
    names = [n for n in names if _has_wave(vf, n)][:max_sig]
    if not names:
        return "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 680 40'/>"

    W, ROW_H, LEFT, RIGHT = 680, 22, 150, 20
    H = 40 + ROW_H * len(names)
    plot_w = W - LEFT - RIGHT
    total = float(vf.duration) or 1.0

    def x(t):
        return LEFT + plot_w * (float(t) / total)

    out = [
        "<svg viewBox='0 0 %d %d' width='100%%' xmlns='http://www.w3.org/2000/svg'>" % (W, H),
        "<title>%s 功能仿真波形</title>" % title,
        "<rect width='%d' height='%d' fill='none'/>" % (W, H),
    ]
    y0 = 34
    for i, name in enumerate(names):
        y = y0 + i * ROW_H
        sig = vf.signals.get(name)
        is_bus = bool(sig and sig.width > 1)
        tr = _bus_trace(vf, name) if is_bus else vf.trace(name)
        out.append("<text x='8' y='%d' font-size='12' fill='#B5D4F4' "
                   "dominant-baseline='middle'>%s</text>" % (y + ROW_H // 2, name))
        out.append("<line x1='%d' y1='%d' x2='%d' y2='%d' stroke='#5F5E5A' "
                   "stroke-width='0.5'/>" % (LEFT, y + ROW_H - 4, W - RIGHT, y + ROW_H - 4))
        if is_bus:
            out.append("<path d='M%d %d H%d' fill='none' stroke='#85B7EB' "
                       "stroke-width='1.2'/>" % (LEFT, y + 6, W - RIGHT))
            for (t, lv) in tr:
                out.append("<line x1='%.1f' y1='%d' x2='%.1f' y2='%d' stroke='#5F5E5A' "
                           "stroke-width='0.5'/>" % (x(t), y + 2, x(t), y + ROW_H - 4))
        else:
            d = []
            prev = None
            for (t, lv) in tr:
                yy = y + 6 if lv == 1 else y + ROW_H - 6
                if prev is None:
                    d.append("M%.1f %d" % (x(t), yy))
                else:
                    d.append("H%.1f V%d" % (x(t), yy))
                prev = yy
            d.append("H%.1f" % x(total))
            out.append("<path d='%s' fill='none' stroke='#85B7EB' stroke-width='1.2'/>"
                       % " ".join(d))
    out.append("</svg>")
    return "\n".join(out)


# ============================================================
# 一键：绑定 → 网表 → 仿真 → 比对 → 还原
# ============================================================
BIND_TCL = """\
package require ::quartus::project
project_open %(proj)s
set_global_assignment -name TOP_LEVEL_ENTITY %(module)s
project_close
"""

# ⚠️ 2026-09-24 实测订正：向量源**不是** `.qsf` 里的 `VECTOR_SOURCE_FILE`
#    （那个名字 Quartus 9.1 不认，实测报
#     `No valid vector source file specified and default file "puzzle.cvwf" does not exist`）。
#    9.1 的正确做法是 **`quartus_sim` 的命令行选项 `--vector_source=<file>`**
#    （见 `quartus_sim --help`）。→ `CLAUDE.md` §5.3 与 `docs/03` §2.1 已同步订正。


def _quartus(tool: str, *args: str) -> int:
    exe = QUARTUS_BIN / (tool + ".exe")
    if not exe.exists():
        raise SystemExit("✗ 找不到 %s" % exe)
    print("  $ %s %s" % (tool, " ".join(args)))
    return subprocess.call([str(exe)] + list(args), cwd=str(PROJ_DIR))


def cmd_run(module: str) -> int:
    rc = cmd_gen(module)
    if rc:
        return rc

    # ---- 备份 .qsf：整文件备份/还原，保证跑完逐字节相同 ----
    if not QSF.exists():
        raise SystemExit("✗ 找不到 %s" % QSF)
    backup = QSF.read_bytes()

    tcl = PROJ_DIR / "_sim_bind.tcl"
    rel_vwf = "../sim/%s.vwf" % module
    try:
        tcl.write_text(BIND_TCL % {"proj": PROJ_NAME, "module": module},
                       encoding="utf-8")
        print()
        print("== 步骤 A：把被测模块绑成顶层 ==")
        if _quartus("quartus_sh", "-t", str(tcl)):
            print("  ✗ 绑定失败"); return 1
        print("  ✓ 顶层 → %s" % module)

        print()
        print("== 步骤 1：生成功能仿真网表 ==")
        if _quartus("quartus_map", PROJ_NAME, "--generate_functional_sim_netlist"):
            print("  ✗ 生成网表失败"); return 1

        print()
        print("== 步骤 B+3：跑功能仿真（向量源走 --vector_source，结果写回 .vwf）==")
        if _quartus("quartus_sim", PROJ_NAME, "--mode=functional",
                    "--overwrite_waveform=on", "--vector_source=" + rel_vwf):
            print("  ✗ 仿真失败"); return 1
    finally:
        QSF.write_bytes(backup)
        if tcl.exists():
            tcl.unlink()
        print()
        print("  ✓ 已还原 %s（跑完与跑之前逐字节相同）" % QSF.name)

    print()
    print("== 步骤 4：解析结果 + 参考模型比对 ==")
    return cmd_check(module)


# ============================================================
def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    cmd, module = sys.argv[1], sys.argv[2]
    if cmd == "gen":
        return cmd_gen(module)
    if cmd == "check":
        return cmd_check(module)
    if cmd == "run":
        return cmd_run(module)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())

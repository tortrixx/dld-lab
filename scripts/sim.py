#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sim.py —— 模块级功能仿真驱动（Quartus II 9.1 内置仿真器）· 隔离工程版

【设计原则：**仓库是只读的**】
    早期版本直接在 `quartus/puzzle.qsf` 上改顶层、并临时改写 `rtl/*.vhd`，跑完再还原。
    这条路上出过两次事故：
      · ERR-0037：`.qsf` 的 16 行 ld 引脚约束被截断，而且漏还原
      · 2026-09-24：`puzzle_pkg.CLK_HZ` 漏还原（补丁中途报错 → finally 拿不到 saved）
    → **现改为：每次仿真在 `.tmp/sim_<模块>/` 里生成一份隔离工程**
      （RTL 副本 + 补丁 + 该目录自己的 `.qsf`），在那边编译仿真。
      **仓库里的 `.qsf` / `rtl/*.vhd` 一个字节都不会被碰** ——
      既不需要"还原"，也就不会"忘还原"；而且**多个模块可以真并行**。

【标准循环】（`docs/03-仿真验证方案.md` §2）
    写 sim/tb_<模块>.py → 生成 .vwf → 跑 quartus_sim
    → 解析回写结果 + 与参考模型逐点比对 → 渲染波形图 → 写轮次记录 → 单独 commit

【用法】
    python scripts/sim.py run   <模块> [--round N]   # 一键：隔离工程 → 网表 → 仿真 → 比对 → 记录
    python scripts/sim.py gen   <模块>               # 只生成激励 .vwf
    python scripts/sim.py check <模块>               # 只解析现有结果 + 比对
    python scripts/sim.py rounds [<模块>]            # 列出轮次（可追踪）
    python scripts/sim.py diff  <模块> <N1> <N2>     # 对比两轮（可对比）

【轮次记录：可追踪 / 可对比】
    sim/rounds/<模块>/r<NN>.md     —— 人看的：断言表 + 实测值 + 波形图链接
    sim/rounds/<模块>/r<NN>.json   —— 机读的：每条断言的通过情况 + 关键实测值
    轮次号自动递增（`--round` 可指定）。同一模块的相邻轮次直接可比。

【tb 模块契约】
    sim/tb_<模块>.py 必须提供：
        build(b)   —— b 是 vwf.Builder，声明节点 + 驱动激励
        check(vf)  —— vf 是解析后的 vwf.VwfFile，返回 [(名称, 是否通过, 说明), ...]
    可选：
        OBSERVE       —— 中间信号清单；**缺一即报错**（`docs/03` §3.1 第 5 条）
        RTL_PATCHES   —— [(rtl 文件名, 原串, 新串)]，**只作用于本模块的隔离副本**
        DURATION / GRID_PERIOD
"""

import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
QUARTUS_BIN = pathlib.Path(r"C:\QuartusII91\QuartusII91\quartus\bin")
PROJ_NAME = "puzzle"
QUARTUS_DIR = ROOT / "quartus"
SRC_QSF = QUARTUS_DIR / (PROJ_NAME + ".qsf")
SIM_DIR = ROOT / "sim"
ROUNDS_DIR = SIM_DIR / "rounds"
FIG_DIR = ROOT / "docs" / "图"
TMP_DIR = ROOT / ".tmp"

sys.path.insert(0, str(ROOT / "scripts"))
import vwf  # noqa: E402


# ============================================================
# tb 装载
# ============================================================
def tb_path(module):
    return SIM_DIR / ("tb_%s.py" % module)


def load_tb(module):
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


def vwf_path(module):
    return SIM_DIR / (module + ".vwf")


# ============================================================
# 第 2 步：生成激励
# ============================================================
def cmd_gen(module):
    tb = load_tb(module)
    b = vwf.Builder(duration=tb.DURATION, grid_period=tb.GRID_PERIOD)
    tb.build(b)
    out = vwf_path(module)
    b.write(str(out))
    print("  ✓ 已生成激励 %s（时长 %.4g %s）" % (out.relative_to(ROOT), tb.DURATION,
                                                vwf.TIME_UNIT))
    print("  ⚠️ 该文件会被仿真结果覆盖写回 —— 不要手工编辑，改 tb_*.py 重新生成。")
    return 0


# ============================================================
# 解析与断言
# ============================================================
def _has_wave(vf, name):
    """总线本身不会有 TRANSITION_LIST（Builder.write 对总线 continue），要落到比特上查。"""
    if name in vf.transitions:
        return True
    sig = vf.signals.get(name)
    if sig is not None and sig.is_bus:
        return any(("%s[%d]" % (name, b)) in vf.transitions for b in range(sig.width))
    return False


def _bus_trace(vf, name):
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
        v = "X" if v is None else v
        if not out or out[-1][1] != v:
            out.append((t, v))
    return out


def render_svg(vf, names, title, max_sig=24):
    names = [n for n in names if _has_wave(vf, n)][:max_sig]
    if not names:
        return "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 680 40'/>"
    W, ROW_H, LEFT, RIGHT = 680, 22, 150, 20
    H = 40 + ROW_H * len(names)
    plot_w = W - LEFT - RIGHT
    total = float(vf.duration) or 1.0

    def x(t):
        return LEFT + plot_w * (float(t) / total)

    out = ["<svg viewBox='0 0 %d %d' width='100%%' xmlns='http://www.w3.org/2000/svg'>"
           % (W, H),
           "<title>%s 功能仿真波形</title>" % title,
           "<rect width='%d' height='%d' fill='none'/>" % (W, H)]
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
            for (t, _lv) in tr:
                out.append("<line x1='%.1f' y1='%d' x2='%.1f' y2='%d' stroke='#5F5E5A' "
                           "stroke-width='0.5'/>" % (x(t), y + 2, x(t), y + ROW_H - 4))
        else:
            d, prev = [], None
            for (t, lv) in tr:
                yy = y + 6 if lv == 1 else y + ROW_H - 6
                d.append(("M%.1f %d" % (x(t), yy)) if prev is None
                         else ("H%.1f V%d" % (x(t), yy)))
                prev = yy
            d.append("H%.1f" % x(total))
            out.append("<path d='%s' fill='none' stroke='#85B7EB' stroke-width='1.2'/>"
                       % " ".join(d))
    out.append("</svg>")
    return "\n".join(out)


def do_check(module, round_no=None, quiet=False):
    """解析 + 比对 + 出图 + 写轮次记录。返回 (是否全过, results)。"""
    tb = load_tb(module)
    p = vwf_path(module)
    if not p.exists():
        raise SystemExit("✗ 找不到 %s —— 先跑 `sim.py gen %s` 并完成仿真" % (p, module))
    vf = vwf.parse(str(p))

    missing = [n for n in getattr(tb, "OBSERVE", []) if not _has_wave(vf, n)]
    if missing:
        print("  ✗ 观测点缺失（该节点没有 TRANSITION_LIST，说明名字在综合后网表里不存在）：")
        for m in missing:
            print("      %s" % m)
        return False, [("观测点缺失", False, "、".join(missing))]

    results = tb.check(vf)
    n_pass = sum(1 for (_n, ok, _d) in results if ok)

    if not quiet:
        print()
        print("=" * 66)
        print(" %s —— 参考模型逐点比对" % module)
        print("=" * 66)
        for name, ok, detail in results:
            print("  %s %s" % ("✓" if ok else "✗", name))
            if detail:
                for line in str(detail).split("\n"):
                    print("      %s" % line)
        print("-" * 66)
        print("  合计：%d / %d 通过" % (n_pass, len(results)))
        print("=" * 66)

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig = FIG_DIR / ("SIM-%s.svg" % module)
    fig.write_text(render_svg(vf, getattr(tb, "OBSERVE", []), module), encoding="utf-8")
    if not quiet:
        print("  ✓ 波形图已存 %s" % fig.relative_to(ROOT))

    _write_round(module, round_no, results)
    return n_pass == len(results), results


# ============================================================
# 轮次记录（可追踪 / 可对比）
# ============================================================
def _next_round(module):
    d = ROUNDS_DIR / module
    if not d.exists():
        return 1
    ns = []
    for f in d.iterdir():
        m = re.match(r"r(\d+)\.json$", f.name)
        if m:
            ns.append(int(m.group(1)))
    return (max(ns) + 1) if ns else 1


def _write_round(module, round_no, results):
    n = round_no if round_no else _next_round(module)
    d = ROUNDS_DIR / module
    d.mkdir(parents=True, exist_ok=True)
    tb = load_tb(module)
    n_pass = sum(1 for (_n, ok, _d) in results if ok)

    manifest = {
        "module": module,
        "round": n,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_ns": getattr(tb, "DURATION", None),
        "rtl_patches": [list(x) for x in getattr(tb, "RTL_PATCHES", [])],
        "passed": n_pass,
        "total": len(results),
        "all_pass": n_pass == len(results),
        "assertions": [{"name": nm, "ok": bool(ok), "detail": (dt or "")}
                       for (nm, ok, dt) in results],
    }
    (d / ("r%02d.json" % n)).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    md = ["# %s · 第 %02d 轮仿真记录" % (module, n), "",
          "- **时间**：%s" % manifest["timestamp"],
          "- **结论**：%s（%d / %d 通过）" % (
              "✅ 全部通过" if manifest["all_pass"] else "❌ 有失败项", n_pass, len(results)),
          "- **激励时长**：%s ns" % manifest["duration_ns"],
          "- **RTL 补丁**：%s" % (manifest["rtl_patches"] or "无（未改任何 RTL）"),
          "- **波形图**：`docs/图/SIM-%s.svg`" % module, "",
          "| # | 断言 | 结果 | 实测 / 说明 |", "|---|---|---|---|"]
    for i, (nm, ok, dt) in enumerate(results, 1):
        md.append("| %d | %s | %s | %s |" % (
            i, nm, "✅" if ok else "❌", (dt or "").replace("\n", "<br>")))
    md.append("")
    (d / ("r%02d.md" % n)).write_text("\n".join(md), encoding="utf-8")
    print("  ✓ 轮次记录已写 sim/rounds/%s/r%02d.{md,json}" % (module, n))


def cmd_rounds(module=None):
    if not ROUNDS_DIR.exists():
        print("（还没有任何轮次记录）")
        return 0
    mods = [module] if module else sorted(d.name for d in ROUNDS_DIR.iterdir() if d.is_dir())
    for m in mods:
        d = ROUNDS_DIR / m
        if not d.exists():
            print("（%s 无记录）" % m)
            continue
        print("=" * 64)
        print(" %s" % m)
        print("=" * 64)
        for f in sorted(d.glob("r*.json")):
            j = json.loads(f.read_text(encoding="utf-8"))
            bad = "、".join(a["name"][:20] for a in j["assertions"] if not a["ok"])
            print("  r%02d  %s  %2d/%-2d  %s" % (
                j["round"], j["timestamp"], j["passed"], j["total"],
                "✅" if j["all_pass"] else "❌ " + bad))
    return 0


def cmd_diff(module, n1, n2):
    d = ROUNDS_DIR / module
    a = json.loads((d / ("r%02d.json" % int(n1))).read_text(encoding="utf-8"))
    b = json.loads((d / ("r%02d.json" % int(n2))).read_text(encoding="utf-8"))
    print("=" * 66)
    print(" %s：r%02d  →  r%02d" % (module, a["round"], b["round"]))
    print("=" * 66)
    print("  通过数：%d/%d  →  %d/%d" % (a["passed"], a["total"], b["passed"], b["total"]))
    am = {x["name"]: x["ok"] for x in a["assertions"]}
    for x in b["assertions"]:
        old = am.get(x["name"])
        if old is None:
            mark = "（新增）"
        elif x["ok"] and not old:
            mark = "↑ 修好了"
        elif old and not x["ok"]:
            mark = "↓ 退步了"
        else:
            mark = "·"
        print("  %s %s" % ("✓" if x["ok"] else "✗", mark))
        if mark != "·":
            print("      %s" % x["name"])
    return 0


# ============================================================
# 隔离工程 + 一键 run
# ============================================================
def _safe_rmtree(p):
    """删除隔离工程目录 —— **失败不致命**。

    ⚠️ 2026-09-24 实测：隔离工程 `quartus_map` 后约 79 个文件，
    `shutil.rmtree` 会触发执行环境的"批量删除确认"闸门（>50 文件），
    轻则拦下、重则**把进程 SIGTERM 掉** → `check` 那一步永远到不了。
    → 所以这里吞掉异常并给出提示；**清理失败不影响仿真与断言**。
    `.tmp/` 在 `.gitignore` 里，残留无害。
    """
    try:
        shutil.rmtree(p, ignore_errors=True)
        return True
    except Exception as e:                                   # noqa: BLE001
        print("  ⚠️ 隔离工程未能自动清理（%s）—— 无害，可稍后跑 `sim.py clean`" % e)
        return False


def cmd_clean():
    """清理 .tmp/ 下的所有隔离工程。

    ⚠️ 这是**显式**操作，可能触发执行环境的"批量删除确认"闸门 ——
    被拦下时请按提示手动确认，或在文件管理器里删 `.tmp/sim_*`。
    """
    n = 0
    for d in sorted(TMP_DIR.glob("sim_*")):
        if d.is_dir() and _safe_rmtree(d):
            n += 1
    print("  ✓ 已清理 %d 个隔离工程" % n)
    return 0


def _make_isolated_project(module, patches):
    """在 `.tmp/sim_<模块>/` 生成隔离工程：RTL 副本（打补丁）+ 该目录自己的 .qsf。

    **仓库里的 rtl/ 与 quartus/puzzle.qsf 全程只读。**
    """
    # ⚠️ 同样不删目录：直接复用并覆盖同名文件（同名文件必然被重写，不会留陈旧内容）
    d = TMP_DIR / ("sim_" + module)
    (d / "rtl").mkdir(parents=True, exist_ok=True)

    applied = 0
    for f in sorted((ROOT / "rtl").glob("*.vhd")):
        raw = f.read_bytes()
        for (rel, old, new) in patches:
            if pathlib.Path(rel).name != f.name:
                continue
            ob, nb = old.encode("ascii"), new.encode("ascii")
            c = raw.count(ob)
            if c != 1:
                raise SystemExit("✗ 补丁锚点在 %s 里出现 %d 次（要求恰 1 次）：%r"
                                 % (f.name, c, old))
            raw = raw.replace(ob, nb)
            applied += 1
        (d / "rtl" / f.name).write_bytes(raw)
    if applied != len(patches):
        raise SystemExit("✗ 有补丁没被应用（应用 %d / 声明 %d）" % (applied, len(patches)))

    text = SRC_QSF.read_text(encoding="utf-8")
    text = re.sub(r"TOP_LEVEL_ENTITY\s+\S+", "TOP_LEVEL_ENTITY " + module, text)
    if module != "board_test_top":       # 顶层不是自检时，ld 约束会悬挂 → 删掉
        text = "\n".join(
            l for l in text.splitlines()
            if not re.match(r"^\s*set_location_assignment\s+PIN_\d+\s+-to\s+ld\[", l)) + "\n"
    text = re.sub(r"\.\./rtl/(\S+)",
                  lambda m: (d / "rtl" / m.group(1)).resolve().as_posix(), text)
    (d / "puzzle.qsf").write_text(text, encoding="utf-8")
    for extra in ("puzzle.qpf", "puzzle.sdc"):
        src = QUARTUS_DIR / extra
        if src.exists():
            shutil.copy(src, d / extra)
    return d


def _quartus(cwd, tool, *args):
    exe = QUARTUS_BIN / (tool + ".exe")
    if not exe.exists():
        raise SystemExit("✗ 找不到 %s" % exe)
    print("  $ %s %s" % (tool, " ".join(args)))
    return subprocess.call([str(exe)] + list(args), cwd=str(cwd))


def cmd_run(module, round_no=None):
    tb = load_tb(module)
    rc = cmd_gen(module)
    if rc:
        return rc

    patches = getattr(tb, "RTL_PATCHES", [])
    print()
    print("== 步骤 0：在 .tmp/ 生成隔离工程（仓库全程只读）==")
    proj = _make_isolated_project(module, patches)
    print("  ✓ %s（顶层 %s，RTL 补丁 %d 处）" % (proj.relative_to(ROOT), module, len(patches)))

    try:
        print()
        print("== 步骤 1：生成功能仿真网表 ==")
        if _quartus(proj, "quartus_map", PROJ_NAME, "--generate_functional_sim_netlist"):
            print("  ✗ 生成网表失败")
            return 1

        print()
        print("== 步骤 2：跑功能仿真（向量源 = 仓库里的 sim/%s.vwf）==" % module)
        if _quartus(proj, "quartus_sim", PROJ_NAME, "--mode=functional",
                    "--overwrite_waveform=on",
                    "--vector_source=" + vwf_path(module).as_posix()):
            print("  ✗ 仿真失败")
            return 1
    finally:
        # ⚠️⚠️ **不要在这里删隔离工程**。
        #    2026-09-24 实测：隔离工程约 75~79 个文件，删除会触发执行环境的
        #    "批量删除确认"闸门 —— 它会**直接 SIGTERM 掉本进程**，
        #    于是 `try/except` 根本拦不住（不是异常，是信号）→ `check` 那一步永远到不了。
        #    → 结论：**自动清理这件事本身必须去掉**；`.tmp/` 已在 `.gitignore` 里，残留无害。
        #    需要清理时由人显式跑 `python scripts/sim.py clean`。
        print("  ✓ 仓库未被改动（隔离工程留在 %s，需要时跑 `sim.py clean`）"
              % proj.relative_to(ROOT))

    print()
    print("== 步骤 3：解析结果 + 参考模型比对 + 写轮次记录 ==")
    ok, _ = do_check(module, round_no)
    return 0 if ok else 1


# ============================================================
def main():
    argv = sys.argv[1:]
    round_no = None
    if "--round" in argv:
        i = argv.index("--round")
        round_no = int(argv[i + 1])
        del argv[i:i + 2]
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "gen" and len(argv) > 1:
        return cmd_gen(argv[1])
    if cmd == "check" and len(argv) > 1:
        ok, _ = do_check(argv[1], round_no)
        return 0 if ok else 1
    if cmd == "run" and len(argv) > 1:
        return cmd_run(argv[1], round_no)
    if cmd == "rounds":
        return cmd_rounds(argv[1] if len(argv) > 1 else None)
    if cmd == "clean":
        return cmd_clean()
    if cmd == "diff" and len(argv) > 3:
        return cmd_diff(argv[1], argv[2], argv[3])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())

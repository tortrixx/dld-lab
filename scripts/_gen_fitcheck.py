# -*- coding: utf-8 -*-
"""按仓库 quartus/puzzle.qsf 生成临时工程，用于"不动仓库"地验证某个顶层能否编译通过。

用法：
    python scripts/_gen_fitcheck.py <目标目录名> <顶层实体名> [--drop-ld]

  --drop-ld  删除 16 行 ld 引脚约束（puzzle_top 没有 ld 端口时必须加）
"""
import pathlib
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_QSF = ROOT / "quartus" / "puzzle.qsf"


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    out_name, top = sys.argv[1], sys.argv[2]
    drop_ld = "--drop-ld" in sys.argv

    out_dir = ROOT / ".tmp" / out_name
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    shutil.copy(ROOT / "quartus" / "puzzle.qpf", out_dir / "puzzle.qpf")
    shutil.copy(ROOT / "quartus" / "puzzle.sdc", out_dir / "puzzle.sdc")

    text = SRC_QSF.read_text(encoding="utf-8")
    text = re.sub(r"TOP_LEVEL_ENTITY\s+\S+", f"TOP_LEVEL_ENTITY {top}", text)

    removed = 0
    keep = []
    for ln in text.splitlines():
        if drop_ld and re.match(r"^\s*set_location_assignment\s+PIN_\d+\s+-to\s+ld\[", ln):
            removed += 1
            continue
        keep.append(ln)
    text = "\n".join(keep) + "\n"

    def fix(m):
        return ("set_global_assignment -name VHDL_FILE "
                + (ROOT / "rtl" / m.group(1)).resolve().as_posix())

    text = re.sub(r"set_global_assignment\s+-name\s+VHDL_FILE\s+\.\./rtl/(\S+)", fix, text)
    (out_dir / "puzzle.qsf").write_text(text, encoding="utf-8")
    print(f"已生成 {out_dir}：顶层 = {top}，删除 ld 约束 {removed} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# ============================================================
# build.tcl —— Quartus II 9.1 编译驱动脚本
#
# 用法（在仓库根目录执行）：
#     quartus_sh -t scripts/build.tcl                  # 全流程编译当前顶层
#     quartus_sh -t scripts/build.tcl --top puzzle_top # 临时指定顶层实体
#     quartus_sh -t scripts/build.tcl --map-only       # 只做综合（最快，查语法错）
#
# 为什么需要它：
#   1. 直接跑 `quartus_sh --flow compile` 不会打印资源利用率，还要手工去翻报告；
#      本脚本编译完自动把 fit.summary 打印出来，方便随手记录到文档里（对应报告评分项④）
#   2. 模块级验证时经常要临时把顶层换成一个子模块，本脚本支持 --top 一次搞定，
#      不用去改 .qsf（避免忘记改回来）
#
# 注意：--top 只是**本次编译临时生效**，不会写回 .qsf
# ============================================================

package require ::quartus::project
package require ::quartus::flow

set SCRIPT_DIR [file dirname [file normalize [info script]]]
set PROJ_DIR   [file normalize [file join $SCRIPT_DIR .. quartus]]
set PROJ_NAME  puzzle

# ---------- 解析参数 ----------
set top_override ""
set map_only 0

foreach arg $quartus(args) {
    if {$arg eq "--map-only"} {
        set map_only 1
    } elseif {$top_override eq "" && $arg ne "--top"} {
        # 位置参数：视为顶层实体名
        set top_override $arg
    }
}

# 支持 "scripts/build.tcl --top xxx" 形式
set idx [lsearch -exact $quartus(args) "--top"]
if {$idx >= 0 && [llength $quartus(args)] > $idx + 1} {
    set top_override [lindex $quartus(args) [expr {$idx + 1}]]
}

if {![file exists [file join $PROJ_DIR "$PROJ_NAME.qpf"]]} {
    puts "错误：找不到工程文件 [file join $PROJ_DIR "$PROJ_NAME.qpf"]"
    exit 1
}

cd $PROJ_DIR
project_open $PROJ_NAME

if {$top_override ne ""} {
    puts "==> 本次编译临时把顶层实体设为：$top_override"
    set_global_assignment -name TOP_LEVEL_ENTITY $top_override
}

# ---------- 编译 ----------
set rc 0
if {$map_only} {
    puts "==> 只做综合（Analysis & Synthesis）"
    if {[catch {execute_module -tool map} err]} {
        puts "综合失败：$err"
        set rc 1
    }
} else {
    puts "==> 全流程编译（综合 → 布局布线 → 汇编）"
    if {[catch {execute_flow -compile} err]} {
        puts "编译失败：$err"
        set rc 1
    }
}

project_close

# ---------- 打印资源利用率（报告评分项④ 的素材） ----------
set summary [file join $PROJ_DIR "output_files" "$PROJ_NAME.fit.summary"]
if {![file exists $summary]} {
    set summary [file join $PROJ_DIR "$PROJ_NAME.fit.summary"]
}

puts ""
puts "============================================================"
if {[file exists $summary]} {
    puts " 资源利用率（器件 EPM1270T144C5）"
    puts "============================================================"
    set fh [open $summary r]
    while {[gets $fh line] >= 0} {
        puts $line
    }
    close $fh
} else {
    puts " 未找到 fit.summary（可能只跑了综合，或编译失败）"
}
puts "============================================================"

exit $rc

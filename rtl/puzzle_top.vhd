-- ============================================================
--  puzzle_top —— 拼图游戏顶层（整机）
--  所属子系统：顶层（不属于 S1~S7 任何子系统）
--  职责：例化 11 个子模块并按连线表连线；**全项目唯一做引脚绑定的文件**
--  对应需求：全部 11 条 + 3 项提高要求
--
--  【例化方式】一律 component 声明 + port map（CLAUDE.md §10.3）
--    · 一个 component 声明块 = 总体框图 DWG-02 上的一个方框 —— 数量肉眼可数，
--      这也是实验报告评分项⑧（顶层 HDL 代码，10 分）要的形式；
--    · 端口关联一律**具名**（名字 => 信号），不用位置关联；
--    · 代价要如实认：端口列表写两遍，改了子模块端口就必须同步改这里；
--      而 **port map 漏写一个端口不会报错、那根线会静默悬空**。
--    · 声明与例化的顺序 = S1→S7 分组、组内按系统图 DWG-02 从上到下。
--
--  【顶层端口名】一律**不带 i_/o_ 前缀**（seg / cat / dot_row / buzz …），
--    真值源是 quartus/puzzle.qsf 的 -to；子模块端口才带前缀（o_seg / o_dot_row …）。
--    这两个名字必须分别写对 —— 顶层写错不报错、静默悬空。
--
--  【要求 1 的实现位置】SW7 门控在**输出级**（文件末尾六行），
--    不在状态机里 —— 拨动开关到显示熄灭之间因此是**严格零延迟**的。
-- ============================================================

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;
use work.puzzle_pkg.ALL;

entity puzzle_top is
    port (
        clk      : in  std_logic;                      -- 50MHz 系统时钟（板载档位 7）
        sw7      : in  std_logic;                      -- 系统开关，高 = 开
        btn      : in  std_logic;                      -- BTN0 复位键，按下 = 1
        kp_row   : in  std_logic_vector(3 downto 0);   -- 4×4 矩阵键盘行（按下 = 1）
        kp_col   : out std_logic_vector(3 downto 0);   -- 4×4 矩阵键盘列扫描
        seg      : out std_logic_vector(7 downto 0);   -- 数码管段码（高有效）
        cat      : out std_logic_vector(7 downto 0);   -- 数码管位选（低有效）
        dot_row  : out std_logic_vector(7 downto 0);   -- 点阵行（低有效）
        dot_colr : out std_logic_vector(7 downto 0);   -- 点阵红列（高有效）
        dot_colg : out std_logic_vector(7 downto 0);   -- 点阵绿列（高有效）
        buzz     : out std_logic                       -- 蜂鸣器
    );
end entity puzzle_top;

architecture rtl of puzzle_top is

    -- ============================================================
    --  子模块 component 声明
    --  顺序 = 按子系统编号 S1→S7 分组，组内按 docs/图/系统图.html 的 DWG-02
    --  端口逐条照 docs/01 §5 接口定义表抄（那张表是接口的唯一真值源）
    -- ============================================================

    -- 时钟与节拍（S1）
    -- 职责：把 50MHz 变成全系统要用的 5 档单周期使能 ＋ 产生复位（三源或）
    component clk_gen
        port (
            clk        : in  std_logic;
            sys_en     : in  std_logic;
            i_btn_rst  : in  std_logic;                     -- ★ BTN0 复位键（课件 p45（一））
            o_rst      : out std_logic;
            o_tick_8k  : out std_logic;
            o_tick_1k  : out std_logic;
            o_tick_100 : out std_logic;
            o_tick_2hz : out std_logic;
            o_tick_1hz : out std_logic
        );
    end component;

    -- 键盘输入（S2）
    -- 职责：4×4 矩阵键盘扫描 + 80ms 消抖 + 单次按下脉冲（纯器件驱动，不认识"上下左右"）
    component keypad_scan
        port (
            clk         : in  std_logic;
            rst         : in  std_logic;
            i_tick      : in  std_logic;
            i_kp_row    : in  std_logic_vector(3 downto 0);
            o_kp_col    : out std_logic_vector(3 downto 0);
            o_key_code  : out std_logic_vector(4 downto 0);
            o_key_press : out std_logic
        );
    end component;

    -- 游戏控制（S3）
    -- 职责：游戏主状态机、倒计时、关卡切换、键号译码、图案与音效选择、随机种子
    --（只管时间：不含任何坐标运算）
    component game_fsm
        port (
            clk            : in  std_logic;
            rst            : in  std_logic;
            i_tick_1hz     : in  std_logic;
            i_tick_2hz     : in  std_logic;
            i_tick_100     : in  std_logic;
            i_key_code     : in  std_logic_vector(4 downto 0);
            i_key_press    : in  std_logic;
            i_all_locked   : in  std_logic;
            i_solved       : in  std_logic;
            o_state        : out std_logic_vector(2 downto 0);
            o_blink        : out std_logic;
            o_level        : out std_logic;
            o_preview_cnt  : out std_logic_vector(2 downto 0);
            o_game_cnt_bcd : out std_logic_vector(7 downto 0);
            o_pattern_sel  : out std_logic_vector(2 downto 0);
            o_round_start  : out std_logic;
            o_sel_out      : out std_logic;
            o_conf_out     : out std_logic;
            o_dir_out      : out std_logic_vector(3 downto 0);
            o_sound_sel    : out std_logic_vector(2 downto 0);
            o_sound_trig   : out std_logic;
            o_seed_load    : out std_logic;
            o_seed         : out std_logic_vector(7 downto 0)
        );
    end component;

    -- 拼图核心（S4）
    -- 职责：零片锚点 / 选择 / 移动 / 钳位 / 锁定 / 正确性判定（只管空间：不含计数器）
    component puzzle_ctrl
        port (
            clk           : in  std_logic;
            rst           : in  std_logic;
            i_round_start : in  std_logic;
            i_target_mask : in  std_logic_vector(63 downto 0);
            i_rel_mask    : in  mask_arr_t;
            i_height      : in  dim_arr_t;
            i_width       : in  dim_arr_t;
            i_piece_count : in  std_logic_vector(2 downto 0);
            i_rnd         : in  std_logic_vector(7 downto 0);
            o_rnd_step    : out std_logic;
            i_sel         : in  std_logic;
            i_conf        : in  std_logic;
            i_dir         : in  std_logic_vector(3 downto 0);
            o_px_red      : out std_logic_vector(63 downto 0);
            o_px_green    : out std_logic_vector(63 downto 0);
            o_all_locked  : out std_logic;
            o_solved      : out std_logic
        );
    end component;

    -- 图案与随机数据（S5）· 图案查找表
    -- 职责：图案掩码查找表（目标 / 胜利 / 失败图案），纯组合
    component pattern_rom
        port (
            i_sel  : in  std_logic_vector(2 downto 0);
            o_mask : out std_logic_vector(63 downto 0)
        );
    end component;

    -- 图案与随机数据（S5）· 零片形状查找表
    -- 职责：一次输出本关全部零片的相对掩码与包围盒高宽，纯组合
    component piece_rom
        port (
            i_pattern_sel : in  std_logic_vector(2 downto 0);
            o_rel_mask    : out mask_arr_t;
            o_height      : out dim_arr_t;
            o_width       : out dim_arr_t;
            o_count       : out std_logic_vector(2 downto 0)
        );
    end component;

    -- 图案与随机数据（S5）· 伪随机数发生器
    -- 职责：8 位最大长度 LFSR；**不接任何节拍**，由 rnd_step 请求推进
    component rng_lfsr
        port (
            clk         : in  std_logic;
            rst         : in  std_logic;
            i_step      : in  std_logic;
            i_seed_load : in  std_logic;
            i_seed      : in  std_logic_vector(7 downto 0);
            o_rnd       : out std_logic_vector(7 downto 0)
        );
    end component;

    -- 显示子系统（S6）· 显示格式化
    -- 职责：状态 → 8 位 BCD + 熄灭掩码 + 点阵像素多路选择（纯组合，点阵像素的唯一汇合点）
    component disp_format
        port (
            i_state        : in  std_logic_vector(2 downto 0);
            i_level        : in  std_logic;
            i_preview_cnt  : in  std_logic_vector(2 downto 0);
            i_game_cnt_bcd : in  std_logic_vector(7 downto 0);
            i_blink        : in  std_logic;
            i_pattern_mask : in  std_logic_vector(63 downto 0);
            i_px_red       : in  std_logic_vector(63 downto 0);
            i_px_green     : in  std_logic_vector(63 downto 0);
            o_disp_val     : out std_logic_vector(31 downto 0);
            o_blank        : out std_logic_vector(7 downto 0);
            o_px_red       : out std_logic_vector(63 downto 0);
            o_px_green     : out std_logic_vector(63 downto 0)
        );
    end component;

    -- 显示子系统（S6）· 数码管动态扫描
    -- 职责：8 位数码管动态扫描 + BCD→段码译码（两相消隐防鬼影）
    component seg_scan
        port (
            clk        : in  std_logic;
            rst        : in  std_logic;
            i_tick     : in  std_logic;
            i_disp_val : in  std_logic_vector(31 downto 0);
            i_blank    : in  std_logic_vector(7 downto 0);
            o_seg      : out std_logic_vector(7 downto 0);
            o_cat      : out std_logic_vector(7 downto 0)
        );
    end component;

    -- 显示子系统（S6）· 点阵动态扫描
    -- 职责：8×8 双色点阵动态扫描（两相消隐防鬼影），掩码→引脚的唯一映射点
    component dot_matrix_scan
        port (
            clk        : in  std_logic;
            rst        : in  std_logic;
            i_tick     : in  std_logic;
            i_px_red   : in  std_logic_vector(63 downto 0);
            i_px_green : in  std_logic_vector(63 downto 0);
            o_dot_row  : out std_logic_vector(7 downto 0);
            o_dot_colr : out std_logic_vector(7 downto 0);
            o_dot_colg : out std_logic_vector(7 downto 0)
        );
    end component;

    -- 音效输出（S7）
    -- 职责：按事件播放对应音效（8 种），方波由内部寄存器翻转产生
    component buzzer_ctrl
        port (
            clk         : in  std_logic;
            rst         : in  std_logic;
            i_tick_8k   : in  std_logic;
            i_sound_sel : in  std_logic_vector(2 downto 0);
            i_trigger   : in  std_logic;
            o_buzz      : out std_logic
        );
    end component;

    -- ============================================================
    --  内部互连信号（按系统级连线 + 子系统出线逐条建网）
    --  ※ 别名：同一根线上游叫 o_xxx、下游叫 i_xxx，中间必须有一个 s_xxx。
    --     漏建一条 → 下游输入悬空，综合不报错。
    --  ※ 系统级四线（clk / sw7 / btn / kp_row）不需要 s_*：
    --     它们是顶层端口直接进 port map。
    -- ============================================================
    signal s_rst      : std_logic;                     -- 复位（clk_gen 扇出到 6 个子系统）
    signal s_tick_8k  : std_logic;                     -- 8kHz 节拍
    signal s_tick_1k  : std_logic;                     -- 1kHz 节拍
    signal s_tick_100 : std_logic;                     -- 100Hz 节拍
    signal s_tick_2hz : std_logic;                     -- 2Hz 节拍
    signal s_tick_1hz : std_logic;                     -- 1Hz 节拍

    signal s_key_code  : std_logic_vector(4 downto 0); -- 键号 1~16（5 位！16 装不进 4 位）
    signal s_key_press : std_logic;                    -- 单次按下脉冲

    signal s_round_start : std_logic;                  -- 新一局脉冲
    signal s_sel_out     : std_logic;                  -- 转发的"选择"脉冲
    signal s_conf_out    : std_logic;                  -- 转发的"确认"脉冲
    signal s_dir_out     : std_logic_vector(3 downto 0); -- 转发的方向脉冲（含连发）

    signal s_pattern_sel : std_logic_vector(2 downto 0); -- 图案选择（同时驱两个 ROM）

    signal s_seed      : std_logic_vector(7 downto 0); -- 随机种子
    signal s_seed_load : std_logic;                    -- 种子装载脉冲
    signal s_rnd_step  : std_logic;                    -- 请求 LFSR 推进（由 puzzle_ctrl 发）
    signal s_rnd       : std_logic_vector(7 downto 0); -- 当前随机数

    signal s_target_mask  : std_logic_vector(63 downto 0); -- 目标图案（→ 拼图核心）
    signal s_pattern_mask : std_logic_vector(63 downto 0); -- 图案掩码（→ 显示：预览/胜负）

    signal s_rel_mask    : mask_arr_t;                 -- 4 块零片相对掩码
    signal s_height      : dim_arr_t;                  -- 4 块包围盒高
    signal s_width       : dim_arr_t;                  -- 4 块包围盒宽
    signal s_piece_count : std_logic_vector(2 downto 0); -- 本关零片数

    -- ※ 两段 px_red/px_green 同名但不是同一根线，必须配两个网名：
    --    共用一网名的话，点阵会接到 puzzle_ctrl 那一级 →
    --    **预览图案、自检闪烁、胜负图案永远上不了点阵**（且编译不报错）。
    signal s_px_logic_red   : std_logic_vector(63 downto 0); -- 核心出（零片像素）
    signal s_px_logic_green : std_logic_vector(63 downto 0);
    signal s_px_final_red   : std_logic_vector(63 downto 0); -- 格式化后进点阵
    signal s_px_final_green : std_logic_vector(63 downto 0);

    signal s_all_locked : std_logic;                   -- 全部零片已锁定（→ 游戏控制）
    signal s_solved     : std_logic;                   -- 拼对了（→ 游戏控制）

    signal s_state        : std_logic_vector(2 downto 0);  -- 当前状态
    signal s_blink        : std_logic;                     -- 2Hz 方波
    signal s_level        : std_logic;                     -- 关卡号
    signal s_preview_cnt  : std_logic_vector(2 downto 0);  -- 预览倒计时
    signal s_game_cnt_bcd : std_logic_vector(7 downto 0);  -- 拼图倒计时（BCD）

    signal s_sound_sel  : std_logic_vector(2 downto 0); -- 音效选择
    signal s_sound_trig : std_logic;                    -- 音效触发脉冲

    signal s_disp_val : std_logic_vector(31 downto 0);  -- 8 位 BCD
    signal s_blank    : std_logic_vector(7 downto 0);   -- 熄灭掩码

    signal s_seg      : std_logic_vector(7 downto 0);
    signal s_cat      : std_logic_vector(7 downto 0);
    signal s_dot_row  : std_logic_vector(7 downto 0);
    signal s_dot_colr : std_logic_vector(7 downto 0);
    signal s_dot_colg : std_logic_vector(7 downto 0);
    signal s_buzz     : std_logic;

begin

    -- ============================================================
    --  例化（顺序与上面的声明块同序）
    -- ============================================================

    -- 1. 时钟与节拍（S1）
    u_clk_gen : clk_gen
        port map (
            clk        => clk,
            sys_en     => sw7,          -- 系统开关：参与产生复位
            i_btn_rst  => btn,          -- ★ BTN0 复位键（顶层端口，不带前缀）
            o_rst      => s_rst,
            o_tick_8k  => s_tick_8k,
            o_tick_1k  => s_tick_1k,
            o_tick_100 => s_tick_100,
            o_tick_2hz => s_tick_2hz,
            o_tick_1hz => s_tick_1hz
        );

    -- 2. 键盘输入（S2）
    u_keypad_scan : keypad_scan
        port map (
            clk         => clk,
            rst         => s_rst,
            i_tick      => s_tick_1k,   -- 1kHz：扫描 + 80ms 消抖计时
            i_kp_row    => kp_row,      -- 顶层端口直连
            o_kp_col    => kp_col,      -- 顶层端口直连
            o_key_code  => s_key_code,
            o_key_press => s_key_press
        );

    -- 3. 游戏控制（S3）
    u_game_fsm : game_fsm
        port map (
            clk            => clk,
            rst            => s_rst,
            i_tick_1hz     => s_tick_1hz,
            i_tick_2hz     => s_tick_2hz,
            i_tick_100     => s_tick_100,
            i_key_code     => s_key_code,
            i_key_press    => s_key_press,
            i_all_locked   => s_all_locked,
            i_solved       => s_solved,
            o_state        => s_state,
            o_blink        => s_blink,
            o_level        => s_level,
            o_preview_cnt  => s_preview_cnt,
            o_game_cnt_bcd => s_game_cnt_bcd,
            o_pattern_sel  => s_pattern_sel,
            o_round_start  => s_round_start,
            o_sel_out      => s_sel_out,
            o_conf_out     => s_conf_out,
            o_dir_out      => s_dir_out,
            o_sound_sel    => s_sound_sel,
            o_sound_trig   => s_sound_trig,
            o_seed_load    => s_seed_load,
            o_seed         => s_seed
        );

    -- 4. 拼图核心（S4）
    u_puzzle_ctrl : puzzle_ctrl
        port map (
            clk           => clk,
            rst           => s_rst,
            i_round_start => s_round_start,
            i_target_mask => s_target_mask,
            i_rel_mask    => s_rel_mask,
            i_height      => s_height,
            i_width       => s_width,
            i_piece_count => s_piece_count,
            i_rnd         => s_rnd,
            o_rnd_step    => s_rnd_step,
            i_sel         => s_sel_out,
            i_conf        => s_conf_out,
            i_dir         => s_dir_out,
            o_px_red      => s_px_logic_red,
            o_px_green    => s_px_logic_green,
            o_all_locked  => s_all_locked,
            o_solved      => s_solved
        );

    -- 5. 图案与随机数据（S5）
    u_pattern_rom : pattern_rom
        port map (
            i_sel  => s_pattern_sel,
            o_mask => s_target_mask
        );

    u_piece_rom : piece_rom
        port map (
            i_pattern_sel => s_pattern_sel,   -- ★ 与 pattern_rom 同源：零片永远跟着图案走
            o_rel_mask    => s_rel_mask,
            o_height      => s_height,
            o_width       => s_width,
            o_count       => s_piece_count
        );

    u_rng_lfsr : rng_lfsr
        port map (
            clk         => clk,
            rst         => s_rst,
            i_step      => s_rnd_step,        -- ★ 由 puzzle_ctrl 请求推进（不接节拍）
            i_seed_load => s_seed_load,
            i_seed      => s_seed,
            o_rnd       => s_rnd
        );

    -- 6. 显示子系统（S6）
    u_disp_format : disp_format
        port map (
            i_state        => s_state,
            i_level        => s_level,
            i_preview_cnt  => s_preview_cnt,
            i_game_cnt_bcd => s_game_cnt_bcd,
            i_blink        => s_blink,
            i_pattern_mask => s_pattern_mask,  -- 预览图案（要求 4）与胜负图案（要求 9）
            i_px_red       => s_px_logic_red,
            i_px_green     => s_px_logic_green,
            o_disp_val     => s_disp_val,
            o_blank        => s_blank,
            o_px_red       => s_px_final_red,
            o_px_green     => s_px_final_green
        );

    u_seg_scan : seg_scan
        port map (
            clk        => clk,
            rst        => s_rst,
            i_tick     => s_tick_8k,        -- 8kHz：两相消隐下刷新率 500Hz
            i_disp_val => s_disp_val,
            i_blank    => s_blank,
            o_seg      => s_seg,
            o_cat      => s_cat
        );

    u_dot_matrix_scan : dot_matrix_scan
        port map (
            clk        => clk,
            rst        => s_rst,
            i_tick     => s_tick_8k,        -- 8kHz：每行 0.25ms，一帧 2ms → 500Hz
            i_px_red   => s_px_final_red,
            i_px_green => s_px_final_green,
            o_dot_row  => s_dot_row,
            o_dot_colr => s_dot_colr,
            o_dot_colg => s_dot_colg
        );

    -- 7. 音效输出（S7）
    u_buzzer_ctrl : buzzer_ctrl
        port map (
            clk         => clk,
            rst         => s_rst,
            i_tick_8k   => s_tick_8k,
            i_sound_sel => s_sound_sel,
            i_trigger   => s_sound_trig,
            o_buzz      => s_buzz
        );

    -- 图案掩码的第二去处：预览（要求 4）与胜负图案（要求 9）直接上点阵
    s_pattern_mask <= s_target_mask;

    -- ============================================================
    --  输出级门控（要求 1 的唯一实现，docs/01 §1.2 原则三）
    --  SW7 = '0' → 所有显示器件熄灭、蜂鸣器静音，**严格零延迟**：
    --  组合门控发生在输出级，不经过状态机，也不经过复位。
    --  ※ 左边的名字是「顶层器件端口」，不带 o_ 前缀 ——
    --     与子模块端口 o_seg / o_dot_row … 是两套名字，别混。
    -- ============================================================
    dot_row  <= s_dot_row  when sw7 = '1' else (others => '1');   -- 行低有效 → 全 1 = 全灭
    dot_colr <= s_dot_colr when sw7 = '1' else (others => '0');
    dot_colg <= s_dot_colg when sw7 = '1' else (others => '0');
    seg      <= s_seg      when sw7 = '1' else (others => '0');
    cat      <= s_cat      when sw7 = '1' else (others => '1');   -- 位选低有效 → 全 1 = 全灭
    buzz     <= s_buzz     when sw7 = '1' else '0';

end architecture rtl;

-- ============================================================
--  buzzer_ctrl —— 蜂鸣器音效
--  所属子系统：S7 音效输出（DWG-01）
--  职责：蜂鸣器音效产生
--  对应需求：提高要求①（不同场景播放不同音效）
--
--  【设计要点】
--   ① 时基用 i_tick_8k（8kHz，125μs 分辨率）：4kHz 音只需半周期 N=1，正好够用，
--      且省掉一个 26 位的分频计数器。
--   ② 半周期表存 **N-1** 而不是 N：计数器从 N-1 数到 0 共 N 拍，恰为半个周期。
--      存 N 会多数一拍，每种音效的频率全错（2kHz 变成 1.33kHz）。
--   ③ i_trigger 是「**单周期脉冲 ＋ 电平装载**」，实现里没有边沿检测：
--      脉宽必须由发出方保证 1 个 clk（game_fsm.o_sound_trig）。
--      ※ 宽于 1 拍不是"重触发"而是"完全无声"——每拍都会重新装载，计时器永远推进不了。
--   ④ 触发那一拍锁存 i_sound_sel：播放期间（最长 600ms）上游的值可能已变，
--      不锁存会让音调中途跳变。
--   ⑤ 方波靠**内部寄存器 r_buzz** 翻转得到：VHDL-93 不允许读 out 模式的端口，
--      o_buzz <= not o_buzz 这种写法编译不过，且接上输出级门控后读到的还不是内部状态。
-- ============================================================

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;
use work.puzzle_pkg.ALL;

entity buzzer_ctrl is
    port (
        clk         : in  std_logic;
        rst         : in  std_logic;
        i_tick_8k   : in  std_logic;                     -- 8kHz 时基
        i_sound_sel : in  std_logic_vector(2 downto 0);  -- 音效选择
        i_trigger   : in  std_logic;                     -- 触发脉冲（1 个 clk）
        o_buzz      : out std_logic                      -- 方波输出
    );
end entity buzzer_ctrl;

architecture rtl of buzzer_ctrl is

    -- 音效表（模块私有：只有本模块用，放包里反而制造不必要的耦合）
    --   频率推导：f = 8000 / (2 × N)，N = 每隔 N 个 i_tick_8k 翻转一次
    --     N=1 → 4kHz   N=2 → 2kHz   N=4 → 1kHz   N=8 → 500Hz   N=16 → 250Hz
    --   时长推导：时长（拍） = 时长（ms） × 8
    type int_arr8_t is array (0 to 7) of integer;

    -- ★ 存的是 N-1：计数器从 N-1 数到 0 共 N 拍，恰为半个周期
    constant HALF_A : int_arr8_t := (0, 1, 3, 7, 3, 0, 1,  7);  -- 主音（交替音的第一段）
    constant HALF_B : int_arr8_t := (0, 1, 3, 7, 3, 0, 0, 15);  -- 交替音的第二段（仅 6/7 用）
    constant DUR    : int_arr8_t := (0, 240, 160, 640, 400, 480, 3200, 4800);  -- 总时长（拍）
    constant SEG    : int_arr8_t := (0, 0, 0, 0, 0, 0, 800, 1200);             -- 交替段长（拍）

    signal r_half : integer range 0 to 15;               -- 半周期计数（最大 N-1 = 15）
    signal r_dur  : integer range 0 to 4800;             -- 剩余时长（13 位）
    signal r_seg  : integer range 0 to 1200;             -- 当前交替段剩余
    signal r_alt  : std_logic;                           -- 交替相位
    signal r_play : std_logic_vector(2 downto 0);        -- 触发时锁存的音效号
    signal r_buzz : std_logic;                           -- 方波内部寄存器

begin

    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_half <= 0;
                r_dur  <= 0;
                r_seg  <= 0;
                r_alt  <= '0';
                r_play <= "000";
                r_buzz <= '0';
            elsif i_trigger = '1' then
                -- ★ 触发那一拍：锁存音效号并装载三张表
                r_play <= i_sound_sel;
                r_dur  <= DUR   (to_integer(unsigned(i_sound_sel)));
                r_seg  <= SEG   (to_integer(unsigned(i_sound_sel)));
                r_half <= HALF_A(to_integer(unsigned(i_sound_sel)));
                r_alt  <= '0';
                r_buzz <= '0';
            elsif i_tick_8k = '1' and r_dur /= 0 then
                -- 半周期翻转：r_half 从 N-1 数到 0，共 N 拍
                if r_half = 0 then
                    r_buzz <= not r_buzz;      -- ★ 翻转内部寄存器，不是 out 端口
                    if r_alt = '0' then
                        r_half <= HALF_A(to_integer(unsigned(r_play)));
                    else
                        r_half <= HALF_B(to_integer(unsigned(r_play)));
                    end if;
                else
                    r_half <= r_half - 1;
                end if;

                -- 交替段推进（仅 sel 6/7 的 SEG 非零，其余音效 r_seg 恒 0、本节不动作）
                if r_seg /= 0 then
                    if r_seg = 1 then
                        r_alt <= not r_alt;
                        r_seg <= SEG(to_integer(unsigned(r_play)));
                        -- ★ 段边界同步重载半周期计数：否则新段的首个半周期
                        --   会沿用旧计数，产生相位毛刺
                        if r_alt = '0' then
                            r_half <= HALF_B(to_integer(unsigned(r_play)));  -- 即将进入 B 段
                        else
                            r_half <= HALF_A(to_integer(unsigned(r_play)));  -- 即将回到 A 段
                        end if;
                    else
                        r_seg <= r_seg - 1;
                    end if;
                end if;

                r_dur <= r_dur - 1;
                if r_dur = 1 then
                    r_buzz <= '0';             -- 播完静音（覆盖同拍的翻转赋值）
                end if;
            end if;
        end if;
    end process;

    -- ★ 端口只是内部寄存器的"出口"
    o_buzz <= r_buzz;

end architecture rtl;

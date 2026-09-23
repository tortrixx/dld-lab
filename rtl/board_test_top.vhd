-- ============================================================
--  board_test_top —— 硬件自检顶层（上板前的必备件）
--  所属子系统：顶层（不属于 S1~S7 任何子系统）
--  职责：例化子模块并做引脚绑定；**上板自检专用**，不是最终产物但长期保留
--  对应需求：—（服务于"上板前必须确认的 10 项硬件事实"，见 docs/01 §8）
--
--  【为什么需要它】
--   本设计的正确性依赖 10 个无法从文档推断、只能实测的硬件事实
--   （时钟档位 / 键盘行列序与极性 / 点阵与数码管的极性和位序 / BTN0 与 SW7 极性）。
--   把板子只在实验室能用这一约束下的 10 项不确定性**集中到一次实验室行程里**，
--   避免"写完全部代码才发现极性错"。
--
--  【9 个自检阶段（自动轮播，每阶段约 2 秒，ld[15:8] 显示阶段号）】
--    1 全部 LED 以 1Hz 闪烁          → 时钟有、档位对
--    2 点阵逐行点亮（上→下）          → 行序 + 行极性（低有效）
--    3 点阵逐列点亮红色（左→右）      → 列序 + COLR 极性 + bit0 是否在最左
--    4 点阵逐列点亮绿色（左→右）      → COLG 极性
--    5 数码管 DISP0→DISP7 逐个显示 8  → 位选顺序 + 位选低有效
--    6 数码管显示 1 2 3 4 5 6 7 8     → 段码顺序（AA..AP）
--    7 按任意键，对应 LED 点亮        → 键盘行列顺序 + 极性（本阶段只点亮 LED）
--    8 蜂鸣器 500Hz <-> 2kHz 各 1 秒    → 蜂鸣器是无源的、频率可控；之前完全无声
--    9 按住 BTN0：16 个 LED 全亮；松开后自检从阶段 1 重来 → BTN0 极性与复位通路
--
--  【几处如实说明】
--   · 阶段 7 按 docs/01 §8.2 的本意是"停留无限期，直到按过全部 16 键或重新上电"；
--     本实现额外加了 **20 秒超时**，否则在实验室里没按满 16 键就永远看不到阶段 8/9。
--   · 阶段 8 的方波**由本模块自产、不经 buzzer_ctrl**：buzzer_ctrl 的 8 种音效
--     全是定时长的（最长 600ms，播完即静音），而本阶段要的是"一直响、能听出高低"。
--   · 阶段 7 把 16 个 LED 全部让给"键号一位独热"，故该阶段不显示阶段号。
-- ============================================================

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;
use work.puzzle_pkg.ALL;

entity board_test_top is
    port (
        clk       : in  std_logic;                      -- 50MHz（板载档位 7）
        sw7       : in  std_logic;                      -- 系统开关，高 = 开
        btn       : in  std_logic;                      -- BTN0 复位键，按下 = 1
        kp_row    : in  std_logic_vector(3 downto 0);   -- 键盘行（按下 = 1）
        kp_col    : out std_logic_vector(3 downto 0);   -- 键盘列扫描
        seg       : out std_logic_vector(7 downto 0);   -- 数码管段码（高有效）
        cat       : out std_logic_vector(7 downto 0);   -- 数码管位选（低有效）
        dot_row   : out std_logic_vector(7 downto 0);   -- 点阵行（低有效）
        dot_colr  : out std_logic_vector(7 downto 0);   -- 点阵红列（高有效）
        dot_colg  : out std_logic_vector(7 downto 0);   -- 点阵绿列（高有效）
        buzz      : out std_logic;                      -- 蜂鸣器
        ld        : out std_logic_vector(15 downto 0)   -- LD0~LD15（高电平点亮）
    );
end entity board_test_top;

architecture rtl of board_test_top is

    -- ========== 子模块 component 声明（写法同 puzzle_top）==========
    -- 时钟与节拍（S1）
    component clk_gen
        port (
            clk        : in  std_logic;
            sys_en     : in  std_logic;
            i_btn_rst  : in  std_logic;
            o_rst      : out std_logic;
            o_tick_8k  : out std_logic;
            o_tick_1k  : out std_logic;
            o_tick_100 : out std_logic;
            o_tick_2hz : out std_logic;
            o_tick_1hz : out std_logic
        );
    end component;

    -- 键盘输入（S2）
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

    -- 显示子系统（S6）：数码管
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

    -- 显示子系统（S6）：点阵
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

    -- ========== 内部互连信号 ==========
    signal s_rst      : std_logic;
    signal s_tick_8k  : std_logic;
    signal s_tick_1k  : std_logic;
    signal s_tick_100 : std_logic;
    signal s_tick_2hz : std_logic;
    signal s_tick_1hz : std_logic;

    signal s_key_code  : std_logic_vector(4 downto 0);
    signal s_key_press : std_logic;

    signal s_px_red    : std_logic_vector(63 downto 0);
    signal s_px_green  : std_logic_vector(63 downto 0);
    signal s_disp_val  : std_logic_vector(31 downto 0);
    signal s_blank     : std_logic_vector(7 downto 0);

    signal s_seg      : std_logic_vector(7 downto 0);
    signal s_cat      : std_logic_vector(7 downto 0);
    signal s_dot_row  : std_logic_vector(7 downto 0);
    signal s_dot_colr : std_logic_vector(7 downto 0);
    signal s_dot_colg : std_logic_vector(7 downto 0);
    signal s_buzz     : std_logic;
    signal s_ld       : std_logic_vector(15 downto 0);

    -- ========== 自检流程控制 ==========
    signal r_stage     : integer range 1 to 9;      -- 当前阶段号
    signal r_step      : integer range 0 to 7;      -- 阶段内子步（行 / 列 / 数码管位）
    signal r_sub_div   : integer range 0 to 24;     -- tick_100 ÷ 25 → 4Hz 子步脉冲
    signal r_subp      : std_logic;                 -- 0.25s 一次的子步脉冲
    signal r_stage_tmr : integer range 0 to 7;      -- 子步计数：8 步 = 2 秒
    signal r_kp_tmr    : integer range 0 to 79;     -- 阶段 7 的超时计时（80 步 = 20 秒）
    signal r_seen      : std_logic_vector(15 downto 0);  -- 阶段 7：已按过的键

    -- 阶段 1 的 1Hz 方波
    signal r_b1_div : integer range 0 to 49;
    signal r_b1     : std_logic;

    -- 阶段 8 的蜂鸣器方波
    signal r_bz_half : integer range 0 to 7;        -- 半周期计数（N-1）
    signal r_bz_sec  : integer range 0 to 7999;     -- 每 8000 拍（1 秒）换一次音高
    signal r_bz_fast : std_logic;
    signal r_bz      : std_logic;

begin

    -- ============================================================
    -- 例化：4 个叶子模块（S1 / S2 / S6 ×2）
    -- ============================================================
    u_clk_gen : clk_gen
        port map (
            clk        => clk,
            sys_en     => sw7,
            i_btn_rst  => btn,
            o_rst      => s_rst,
            o_tick_8k  => s_tick_8k,
            o_tick_1k  => s_tick_1k,
            o_tick_100 => s_tick_100,
            o_tick_2hz => s_tick_2hz,
            o_tick_1hz => s_tick_1hz
        );

    u_keypad_scan : keypad_scan
        port map (
            clk         => clk,
            rst         => s_rst,
            i_tick      => s_tick_1k,
            i_kp_row    => kp_row,
            o_kp_col    => kp_col,
            o_key_code  => s_key_code,
            o_key_press => s_key_press
        );

    u_seg_scan : seg_scan
        port map (
            clk        => clk,
            rst        => s_rst,
            i_tick     => s_tick_8k,
            i_disp_val => s_disp_val,
            i_blank    => s_blank,
            o_seg      => s_seg,
            o_cat      => s_cat
        );

    u_dot_matrix_scan : dot_matrix_scan
        port map (
            clk        => clk,
            rst        => s_rst,
            i_tick     => s_tick_8k,
            i_px_red   => s_px_red,
            i_px_green => s_px_green,
            o_dot_row  => s_dot_row,
            o_dot_colr => s_dot_colr,
            o_dot_colg => s_dot_colg
        );

    -- ============================================================
    -- 子步脉冲：tick_100 ÷ 25 = 4Hz（0.25 秒一次）
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if s_rst = '1' then
                r_sub_div <= 0;
                r_subp    <= '0';
            elsif s_tick_100 = '1' then
                r_subp <= '0';
                if r_sub_div = 24 then
                    r_sub_div <= 0;
                    r_subp    <= '1';
                else
                    r_sub_div <= r_sub_div + 1;
                end if;
            end if;
        end if;
    end process;

    -- ============================================================
    -- 阶段 1 的 1Hz 方波：tick_100 ÷ 50 后翻转（100Hz ÷ 2 ÷ 50 = 1Hz）
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if s_rst = '1' then
                r_b1_div <= 0;
                r_b1     <= '0';
            elsif s_tick_100 = '1' then
                if r_b1_div = 49 then
                    r_b1_div <= 0;
                    r_b1     <= not r_b1;
                else
                    r_b1_div <= r_b1_div + 1;
                end if;
            end if;
        end if;
    end process;

    -- ============================================================
    -- 阶段 8 的蜂鸣器：500Hz（半周期 8 拍）<-> 2kHz（半周期 2 拍），每 1 秒换一次
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if s_rst = '1' then
                r_bz_half <= 0;
                r_bz_sec  <= 0;
                r_bz_fast <= '0';
                r_bz      <= '0';
            elsif s_tick_8k = '1' then
                -- 每 8000 拍（1 秒）切换音高
                if r_bz_sec = 7999 then
                    r_bz_sec  <= 0;
                    r_bz_fast <= not r_bz_fast;
                else
                    r_bz_sec <= r_bz_sec + 1;
                end if;
                -- 半周期翻转
                if r_bz_half = 0 then
                    r_bz <= not r_bz;
                    if r_bz_fast = '1' then
                        r_bz_half <= 1;      -- 2 拍半周期 → 2kHz
                    else
                        r_bz_half <= 7;      -- 8 拍半周期 → 500Hz
                    end if;
                else
                    r_bz_half <= r_bz_half - 1;
                end if;
            end if;
        end if;
    end process;

    -- ============================================================
    -- 自检流程：阶段推进 + 阶段内子步推进
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if s_rst = '1' then
                r_stage     <= 1;
                r_step      <= 0;
                r_stage_tmr <= 0;
                r_kp_tmr    <= 0;
                r_seen      <= (others => '0');
            else
                -- 记录"哪些键按过"（阶段 7 用）
                if s_key_press = '1' and unsigned(s_key_code) /= 0 then
                    r_seen(to_integer(unsigned(s_key_code)) - 1) <= '1';
                end if;

                if r_subp = '1' then
                    -- 阶段内子步（行 / 列 / 数码管位）推进
                    if r_step = 7 then
                        r_step <= 0;
                    else
                        r_step <= r_step + 1;
                    end if;

                    if r_stage = 7 then
                        -- 阶段 7：按键全按过 或 超时 20 秒才往下走
                        if r_seen = "1111111111111111" or r_kp_tmr = 79 then
                            r_stage  <= 8;
                            r_step   <= 0;
                            r_kp_tmr <= 0;
                        else
                            r_kp_tmr <= r_kp_tmr + 1;
                        end if;
                    else
                        -- 其余阶段：8 个子步 = 2 秒
                        if r_stage_tmr = 7 then
                            r_stage_tmr <= 0;
                            r_step      <= 0;
                            if r_stage = 9 then
                                r_stage <= 1;            -- 阶段 9 播完回到阶段 1 循环
                            else
                                r_stage <= r_stage + 1;
                            end if;
                        else
                            r_stage_tmr <= r_stage_tmr + 1;
                        end if;
                    end if;
                end if;
            end if;
        end if;
    end process;

    -- ============================================================
    -- 各阶段的点阵画面（纯组合）
    -- ============================================================
    process (r_stage, r_step)
    begin
        s_px_red   <= MASK_ZERO;
        s_px_green <= MASK_ZERO;

        case r_stage is
            when 2 =>                                     -- 逐行点亮（上→下）
                case r_step is
                    when 0 => s_px_red <= x"00000000000000FF";
                    when 1 => s_px_red <= x"000000000000FF00";
                    when 2 => s_px_red <= x"0000000000FF0000";
                    when 3 => s_px_red <= x"00000000FF000000";
                    when 4 => s_px_red <= x"000000FF00000000";
                    when 5 => s_px_red <= x"0000FF0000000000";
                    when 6 => s_px_red <= x"00FF000000000000";
                    when others => s_px_red <= x"FF00000000000000";
                end case;

            when 3 =>                                     -- 逐列点亮红色（左→右）
                case r_step is
                    when 0 => s_px_red <= x"0101010101010101";
                    when 1 => s_px_red <= x"0202020202020202";
                    when 2 => s_px_red <= x"0404040404040404";
                    when 3 => s_px_red <= x"0808080808080808";
                    when 4 => s_px_red <= x"1010101010101010";
                    when 5 => s_px_red <= x"2020202020202020";
                    when 6 => s_px_red <= x"4040404040404040";
                    when others => s_px_red <= x"8080808080808080";
                end case;

            when 4 =>                                     -- 逐列点亮绿色（左→右）
                case r_step is
                    when 0 => s_px_green <= x"0101010101010101";
                    when 1 => s_px_green <= x"0202020202020202";
                    when 2 => s_px_green <= x"0404040404040404";
                    when 3 => s_px_green <= x"0808080808080808";
                    when 4 => s_px_green <= x"1010101010101010";
                    when 5 => s_px_green <= x"2020202020202020";
                    when 6 => s_px_green <= x"4040404040404040";
                    when others => s_px_green <= x"8080808080808080";
                end case;

            when 9 =>                                     -- 阶段 9：全黄，指示"请按 BTN0"
                s_px_red   <= (others => '1');
                s_px_green <= (others => '1');

            when others =>
                null;                                     -- 其余阶段点阵熄灭
        end case;
    end process;

    -- ============================================================
    -- 各阶段的数码管画面（纯组合）
    -- ============================================================
    process (r_stage, r_step, s_key_code)
        variable v_key  : integer range 0 to 31;
        variable v_tens : integer range 0 to 3;
        variable v_ones : integer range 0 to 9;
    begin
        s_disp_val <= (others => '0');
        s_blank    <= (others => '1');                    -- 默认 8 位全灭

        case r_stage is
            when 5 =>                                     -- 逐个位选，只点亮第 r_step 位
                s_disp_val <= x"88888888";
                s_blank    <= not (std_logic_vector(to_unsigned(1, 8) sll r_step));

            when 6 =>                                     -- 段码顺序：DISP0~DISP7 显示 1~8
                s_disp_val <= x"87654321";
                s_blank    <= (others => '0');

            when 7 =>                                     -- 显示当前键号的十进制两位
                v_key := to_integer(unsigned(s_key_code));
                if v_key >= 10 then
                    v_tens := 1;
                    v_ones := v_key - 10;
                else
                    v_tens := 0;
                    v_ones := v_key;
                end if;
                s_disp_val(3 downto 0) <= std_logic_vector(to_unsigned(v_ones, 4));
                s_disp_val(7 downto 4) <= std_logic_vector(to_unsigned(v_tens, 4));
                s_blank(0) <= '0';
                if v_tens /= 0 then
                    s_blank(1) <= '0';
                else
                    s_blank(1) <= '1';
                end if;

            when others =>                                -- 其余阶段：DISP7 显示阶段号
                s_disp_val(31 downto 28) <=
                    std_logic_vector(to_unsigned(r_stage, 4));
                s_blank(7) <= '0';
        end case;
    end process;

    -- ============================================================
    -- 各阶段的 LED 画面（纯组合）
    -- ============================================================
    process (r_stage, r_step, r_b1, s_key_code)
        variable v_key : integer range 0 to 31;
    begin
        v_key := to_integer(unsigned(s_key_code));

        if r_stage = 7 then
            -- 阶段 7：16 个 LED 全部让给"键号一位独热"（键号 = 亮灯序号）
            if v_key >= 1 then
                s_ld <= std_logic_vector(to_unsigned(1, 16) sll (v_key - 1));
            else
                s_ld <= (others => '0');
            end if;
        else
            s_ld(15 downto 8) <= std_logic_vector(to_unsigned(r_stage, 8));  -- 阶段号
            if r_stage = 1 then
                s_ld(7 downto 0) <= (others => r_b1);       -- 阶段 1：8 个 LED 以 1Hz 闪烁
            else
                s_ld(7 downto 0) <= std_logic_vector(to_unsigned(r_step + 1, 8));  -- 子步号
            end if;
        end if;
    end process;

    -- ============================================================
    -- 输出级：SW7 门控（要求 1，严格零延迟）+ BTN0 直读
    --   按住 BTN0 时 16 个 LED 全亮 —— 这一条走 btn 的**直读通路**，
    --   组合越权于复位之上，用来一次验掉"线接对了"与"复位生效了"两件事。
    -- ============================================================
    seg      <= s_seg      when sw7 = '1' else (others => '0');
    cat      <= s_cat      when sw7 = '1' else (others => '1');        -- 低有效 → 全灭
    dot_row  <= s_dot_row  when sw7 = '1' else (others => '1');        -- 低有效 → 全灭
    dot_colr <= s_dot_colr when sw7 = '1' else (others => '0');
    dot_colg <= s_dot_colg when sw7 = '1' else (others => '0');
    buzz     <= s_buzz     when sw7 = '1' else '0';

    -- 阶段 8 之外：蜂鸣器静音
    s_buzz <= r_bz when r_stage = 8 else '0';
    ld     <= (others => '1') when btn = '1' else s_ld;

end architecture rtl;

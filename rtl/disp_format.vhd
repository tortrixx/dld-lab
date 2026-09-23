-- ============================================================
--  disp_format —— 显示格式化（纯组合）
--  所属子系统：S6 显示子系统（DWG-01）
--  职责：显示总入口：状态 → 8 位 BCD + 熄灭掩码 + 点阵像素多路选择
--  对应需求：1（自检闪烁）、2（待机显 5）、3（关卡号）、4（预览图案）、
--            5（倒计时显示）、9（胜负图案）
--
--  【设计要点】
--   ① 纯组合，无时钟：给输入立刻出输出，最容易仿真（可 100% 覆盖）。
--   ② 点阵这一路是本模块的**多路选择点**：自检全黄闪烁、预览完整图案、
--      游戏中的零片像素、胜负图案 —— 四者在此按状态选一路。
--      少了它，预览与自检画面全项目没有模块能产生（docs/01 §5.9）。
--   ③ 倒计时用 BCD：i_game_cnt_bcd 的 (7..4) 直接就是十位、(3..0) 就是个位，
--      **不做任何 /10 mod10 运算** → 不综合出除法器（docs/02 §11.4）。
--   ④ 所有输出在任何状态下都被赋值（开头给默认值）→ 不会产生 latch。
-- ============================================================

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;
use work.puzzle_pkg.ALL;

entity disp_format is
    port (
        i_state        : in  std_logic_vector(2 downto 0);   -- 当前状态
        i_level        : in  std_logic;                      -- 关卡（0 = 第一关）
        i_preview_cnt  : in  std_logic_vector(2 downto 0);   -- 预览倒计时值
        i_game_cnt_bcd : in  std_logic_vector(7 downto 0);   -- 拼图倒计时（BCD）
        i_blink        : in  std_logic;                      -- 2Hz 方波，自检闪烁用
        i_pattern_mask : in  std_logic_vector(63 downto 0);  -- 图案掩码（预览 / 胜负）
        i_px_red       : in  std_logic_vector(63 downto 0);  -- 来自 puzzle_ctrl 的零片像素
        i_px_green     : in  std_logic_vector(63 downto 0);
        o_disp_val     : out std_logic_vector(31 downto 0);  -- 8 位 BCD
        o_blank        : out std_logic_vector(7 downto 0);   -- 熄灭掩码（1 = 灭）
        o_px_red       : out std_logic_vector(63 downto 0);  -- 最终上点阵的红 / 绿像素
        o_px_green     : out std_logic_vector(63 downto 0)
    );
end entity disp_format;

architecture rtl of disp_format is
begin

    -- ============================================================
    -- 点阵内容选择（纯组合，与下面的数码管映射同一个状态维度）
    -- ============================================================
    process (i_state, i_blink, i_pattern_mask, i_px_red, i_px_green)
    begin
        case i_state is
            when S_SELF_TEST =>                       -- 自检：全黄，2Hz 通断
                o_px_red   <= (others => i_blink);    -- ★ 64 位全等于 i_blink
                o_px_green <= (others => i_blink);    --   红+绿同亮 = 黄
            when S_IDLE =>                            -- 待机：全灭
                o_px_red   <= (others => '0');
                o_px_green <= (others => '0');
            when S_PREVIEW =>                         -- 预览：完整目标图案（红）
                o_px_red   <= i_pattern_mask;
                o_px_green <= (others => '0');
            when S_PLAYING =>                         -- 游戏中：透传零片像素
                o_px_red   <= i_px_red;
                o_px_green <= i_px_green;
            when others =>                            -- S_WIN / S_FAIL：胜负图案（红）
                o_px_red   <= i_pattern_mask;
                o_px_green <= (others => '0');
        end case;
    end process;

    -- ============================================================
    -- 数码管内容选择（与点阵同一个状态维度）
    --   显示分工：DISP7 = 预览倒计时（待机时固定显 5）
    --             DISP4/DISP3 = 拼图倒计时两位十进制
    --             DISP0 = 关卡号
    -- ============================================================
    process (i_state, i_level, i_preview_cnt, i_game_cnt_bcd, i_blink)
        variable v_lvl : integer range 1 to 2;       -- 关卡号的显示值（level 0/1 → 1/2）
    begin
        -- ★ i_level 是 0/1，显示关卡号必须 +1；用 if 直接映射（不写成
        --   "000" & i_level 这种**类型不明确**的拼接，Quartus 会报
        --   "can't determine definition of operator &"）。
        if i_level = '0' then
            v_lvl := 1;
        else
            v_lvl := 2;
        end if;

        o_disp_val <= (others => '0');
        o_blank    <= (others => '1');               -- 默认：8 位全灭
        case i_state is
            when S_SELF_TEST =>
                o_disp_val <= x"88888888";           -- 8 位全 "8"
                o_blank    <= (others => not i_blink);  -- ★ 与点阵同相：blink=1 亮、=0 灭
            when S_IDLE =>
                o_disp_val(31 downto 28) <= x"5";    -- DISP7 = 5（要求 2）
                o_blank(7) <= '0';
                o_disp_val(3 downto 0) <= std_logic_vector(to_unsigned(v_lvl, 4));
                o_blank(0) <= '0';                   -- DISP0 = 关卡号（要求 3）
            when S_PREVIEW =>
                o_disp_val(31 downto 28) <= '0' & i_preview_cnt;  -- ★ 3 位零扩展到 4 位
                o_blank(7) <= '0';
                o_disp_val(3 downto 0) <= std_logic_vector(to_unsigned(v_lvl, 4));
                o_blank(0) <= '0';
            when S_PLAYING =>
                o_disp_val(19 downto 16) <= i_game_cnt_bcd(7 downto 4);   -- DISP4 = 十位
                o_disp_val(15 downto 12) <= i_game_cnt_bcd(3 downto 0);   -- DISP3 = 个位
                if i_game_cnt_bcd(7 downto 4) = "0000" then
                    o_blank(4) <= '1';               -- ★ 前导零熄灭（0x09 显示 "9" 而不是 "09"）
                else
                    o_blank(4) <= '0';
                end if;
                o_blank(3) <= '0';                   -- 个位恒亮（"30" 的 0 是有效数字）
                o_disp_val(3 downto 0) <= std_logic_vector(to_unsigned(v_lvl, 4));
                o_blank(0) <= '0';
            when others =>                           -- S_WIN / S_FAIL：只保留关卡号
                o_disp_val(3 downto 0) <= std_logic_vector(to_unsigned(v_lvl, 4));
                o_blank(0) <= '0';
        end case;
    end process;

end architecture rtl;

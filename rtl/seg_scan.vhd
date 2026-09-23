-- ============================================================
--  seg_scan —— 8 位数码管动态扫描
--  所属子系统：S6 显示子系统（DWG-01）
--  职责：8 位数码管动态扫描 + BCD→段码译码
--  对应需求：2（待机显 5）、3（关卡号）、4（预览倒计时）、5（拼图倒计时）
--
--  【设计要点】
--   ① 两相扫描（消隐 + 显示）：切换位选**前**先保持一整拍 o_seg 全灭，
--      下一相在同一时钟沿切位选并给出新段码 → 防鬼影。
--      "先灭→再切→再亮"是三相叙事的残留；同一条时钟沿内的赋值不存在先后。
--   ② 刷新率 = i_tick / (8 位 × 2 相)。i_tick = 8kHz → 每位 0.25ms、
--      一帧 2ms → 500Hz（用 1kHz 时只有 62.5Hz，会闪）。
--   ③ 位选低有效：o_cat(0) = DISP0（最右），与手册 CAT0→DISP0 一致。
-- ============================================================

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;
use work.puzzle_pkg.ALL;

entity seg_scan is
    port (
        clk        : in  std_logic;
        rst        : in  std_logic;
        i_tick     : in  std_logic;                     -- 8kHz
        i_disp_val : in  std_logic_vector(31 downto 0); -- 8 位 BCD，(4k+3..4k) → DISPk
        i_blank    : in  std_logic_vector(7 downto 0);  -- 熄灭掩码，1 = 该位熄灭
        o_seg      : out std_logic_vector(7 downto 0);  -- 段码，高有效（AA..AG,AP）
        o_cat      : out std_logic_vector(7 downto 0)   -- 位选，低有效（0 = DISP0）
    );
end entity seg_scan;

architecture rtl of seg_scan is

    -- BCD → 7 段段码（共阴极、高有效；段位与编码见 docs/02 §5.4 的表）
    -- 放在 architecture 声明区，是**模块私有**的纯函数
    function seg_decode(b : std_logic_vector(3 downto 0))
        return std_logic_vector is
    begin
        case b is
            when "0000" => return x"3F";   -- 0
            when "0001" => return x"06";   -- 1
            when "0010" => return x"5B";   -- 2
            when "0011" => return x"4F";   -- 3
            when "0100" => return x"66";   -- 4
            when "0101" => return x"6D";   -- 5
            when "0110" => return x"7D";   -- 6
            when "0111" => return x"07";   -- 7
            when "1000" => return x"7F";   -- 8
            when "1001" => return x"6F";   -- 9
            when others => return x"00";   -- ★ 必须有：防 latch；非法 BCD 一律全灭
        end case;
    end function;

    signal r_digit    : unsigned(2 downto 0);   -- 位选计数器 0~7
    signal r_blank_ph : std_logic;              -- 消隐/显示两相

begin

    -- ============================================================
    -- 位计数器 + 相位机
    --   相 0（消隐）：段码全灭、位选保持
    --   相 1（显示）：同一时钟沿切位选 + 给出该位段码
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_digit    <= "000";
                r_blank_ph <= '0';
            elsif i_tick = '1' then
                r_blank_ph <= not r_blank_ph;      -- 在消隐/显示两相间翻转
                if r_blank_ph = '1' then           -- 显示相结束时进位
                    r_digit <= r_digit + 1;        -- 3 位 unsigned 自然回绕 7→0
                end if;
            end if;
        end if;
    end process;

    -- ============================================================
    -- 段码 / 位选输出
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then                      -- 复位到全灭
                o_seg <= (others => '0');
                o_cat <= (others => '1');          -- 位选低有效 → 全 1 = 全灭
            elsif r_blank_ph = '0' then            -- 消隐相：段码全灭，位选保持
                o_seg <= (others => '0');
            else                                   -- 显示相：切位选 + 给段码
                o_cat <= not (std_logic_vector(to_unsigned(1, 8) sll to_integer(r_digit)));
                if i_blank(to_integer(r_digit)) = '1' then
                    o_seg <= (others => '0');
                else
                    o_seg <= seg_decode(i_disp_val(4*to_integer(r_digit)+3
                                                   downto 4*to_integer(r_digit)));
                end if;
            end if;
        end if;
    end process;

end architecture rtl;

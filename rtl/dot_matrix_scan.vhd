-- ============================================================
--  dot_matrix_scan —— 8×8 双色点阵动态扫描
--  所属子系统：S6 显示子系统（DWG-01）
--  职责：8×8 双色点阵动态扫描（含消隐防鬼影）
--  对应需求：6（选中变绿）、7（移动）、9（判定）、10（第二关）
--
--  【设计要点】
--   ① 本模块是**全项目唯一一处"掩码 → 引脚"的映射**：
--      位序约定（bit0 = 左上角、行内 bit0 = 最左列）与硬件天然对齐，
--      故此处 dot_colr <= px_red(8r+7 downto 8r) **无需任何位序翻转**。
--   ② 两相扫描（消隐 + 显示），与 seg_scan 结构对称：
--      切行前先保持一整拍所有行拉高（低有效 → 全灭）。
--   ③ 刷新率 = i_tick / (8 行 × 2 相)：i_tick = 8kHz → 每行 0.25ms、
--      一帧 2ms → 500Hz。
-- ============================================================

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;
use work.puzzle_pkg.ALL;

entity dot_matrix_scan is
    port (
        clk         : in  std_logic;
        rst         : in  std_logic;
        i_tick      : in  std_logic;                     -- 8kHz
        i_px_red    : in  std_logic_vector(63 downto 0); -- 红色像素掩码
        i_px_green  : in  std_logic_vector(63 downto 0); -- 绿色像素掩码
        o_dot_row   : out std_logic_vector(7 downto 0);  -- 行，低有效
        o_dot_colr  : out std_logic_vector(7 downto 0);  -- 红列，高有效
        o_dot_colg  : out std_logic_vector(7 downto 0)   -- 绿列，高有效
    );
end entity dot_matrix_scan;

architecture rtl of dot_matrix_scan is

    signal r_row      : unsigned(2 downto 0);   -- 行计数器 0~7
                                                -- （★ 必须是 unsigned：裸 slv 没有 +1）
    signal r_blank_ph : std_logic;              -- 消隐/显示两相

begin

    -- ============================================================
    -- 行计数器 + 相位机（与 seg_scan 完全对称）
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_row      <= "000";
                r_blank_ph <= '0';
            elsif i_tick = '1' then
                r_blank_ph <= not r_blank_ph;   -- 在消隐/显示两相间翻转
                if r_blank_ph = '1' then        -- 显示相结束时进位
                    r_row <= r_row + 1;         -- 3 位 unsigned 自然回绕 7→0
                end if;
            end if;
        end if;
    end process;

    -- ============================================================
    -- 行 / 列输出
    --   消隐相：整屏全灭（行全高 = 无行选中，列同时清零作第二道保险）
    --   显示相：切行 + 给出该行的红/绿列数据
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then                       -- 复位到全灭
                o_dot_row  <= (others => '1');
                o_dot_colr <= (others => '0');
                o_dot_colg <= (others => '0');
            elsif r_blank_ph = '0' then             -- 消隐相：全灭
                o_dot_row  <= (others => '1');
                o_dot_colr <= (others => '0');
                o_dot_colg <= (others => '0');
            else                                     -- 显示相
                o_dot_row  <= not (std_logic_vector(to_unsigned(1, 8) sll to_integer(r_row)));
                o_dot_colr <= i_px_red  (8*to_integer(r_row)+7 downto 8*to_integer(r_row));
                o_dot_colg <= i_px_green(8*to_integer(r_row)+7 downto 8*to_integer(r_row));
            end if;
        end if;
    end process;

end architecture rtl;

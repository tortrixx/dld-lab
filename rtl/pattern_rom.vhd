-- ============================================================
--  pattern_rom —— 图案查找表
--  所属子系统：S5 图案与随机数据（DWG-01）
--  职责：图案掩码查找表（目标/胜利/失败图案）
--  对应需求：4（预览完整图案）、9（胜负图案）、10（第二关图案）
--
--  【设计要点】
--   ① 纯组合，无时钟。常量表在编译期折叠，不消耗触发器。
--   ② 常量来自 puzzle_pkg，本模块只做"选择"，不定义数据。
--   ③ ⚠️ i_sel = 3 / 4 时输出的是**显示图案**，不是"目标掩码"：
--      这两个编码只出现在 S_WIN / S_FAIL，此时 puzzle_ctrl 的
--      o_solved 会恒为 '0' —— 所以"全锁但没拼对"这条判失败必须
--      限定在 game_fsm 的 S_PLAYING 分支里检查（docs/02 §10.8 / §12.6）。
-- ============================================================

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;
use work.puzzle_pkg.ALL;

entity pattern_rom is
    port (
        i_sel  : in  std_logic_vector(2 downto 0);   -- 图案选择
        o_mask : out std_logic_vector(63 downto 0)   -- 图案掩码
    );
end entity pattern_rom;

architecture rtl of pattern_rom is
begin

    process (i_sel)
    begin
        case i_sel is
            when "000"  => o_mask <= L1_TARGET_MASK;    -- 第一关目标：4×3 实心矩形
            when "001"  => o_mask <= L2_TARGET_MASK;    -- 第二关目标：向上箭头
            when "010"  => o_mask <= L2B_TARGET_MASK;   -- 第二关目标：向下箭头
            when "011"  => o_mask <= WIN_MASK;          -- ⚠️ 显示图案（S_WIN 用）
            when "100"  => o_mask <= FAIL_MASK;         -- ⚠️ 显示图案（S_FAIL 用）
            when others => o_mask <= (others => '0');   -- ★ 必须，防 latch
        end case;
    end process;

end architecture rtl;

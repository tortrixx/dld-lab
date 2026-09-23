-- ============================================================
--  piece_rom —— 零片形状查找表
--  所属子系统：S5 图案与随机数据（DWG-01）
--  职责：零片形状查找表（相对掩码 + 宽高）
--  对应需求：6（选择）、7（移动）、9（判定）
--
--  【设计要点】
--   ① 纯组合，无时钟。一次输出 4 块（而不是"给序号查一块"）：
--      顶层例化全部子模块，若只能查一块，puzzle_ctrl 就得自己例化 4 份
--      —— 框图上会多出一个藏在 puzzle_ctrl 里的方框（docs/01 §5.6）。
--   ② i_pattern_sel 与 pattern_rom.i_sel **同源**（game_fsm.o_pattern_sel）：
--      零片永远跟着图案走，结构上杜绝"图案是下箭头、零片是上箭头"的错配。
--   ③ o_height / o_width 用位串字面量（"011"），不能用整数聚合
--      （dim_arr_t 的元素是 std_logic_vector，整数聚合类型不匹配）。
--   ④ 第一关第 4 槽填全 0，由 o_count = 3 保证它不被读到。
--   ⑤ 所有零片的包围盒 ≤ 3×3，且相对掩码只在前 3 行 × 前 3 列有非零位
--      —— puzzle_ctrl 的 place() 依赖这一条（见 puzzle_pkg 的 PIECE_MAX_DIM）。
-- ============================================================

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;
use work.puzzle_pkg.ALL;

entity piece_rom is
    port (
        i_pattern_sel : in  std_logic_vector(2 downto 0);  -- 与 pattern_rom.i_sel 同源
        o_rel_mask    : out mask_arr_t;                    -- 4 块相对掩码
        o_height      : out dim_arr_t;                     -- 4 块包围盒高
        o_width       : out dim_arr_t;                     -- 4 块包围盒宽
        o_count       : out std_logic_vector(2 downto 0)   -- 本关零片数（3 或 4）
    );
end entity piece_rom;

architecture rtl of piece_rom is
begin

    process (i_pattern_sel)
    begin
        case i_pattern_sel is
            when "000" =>                            -- 第一关：3 块 + 1 个占位槽
                o_rel_mask <= (L1_P0, L1_P1, L1_P2, MASK_ZERO);
                o_height   <= ("011", "010", "001", "000");
                o_width    <= ("011", "010", "011", "000");
                o_count    <= "011";                 -- 3
            when "001" =>                            -- 第二关 · 向上箭头
                o_rel_mask <= (L2_P0, L2_P1, L2_P2, L2_P3);
                o_height   <= ("011", "011", "010", "001");
                o_width    <= ("011", "011", "010", "010");
                o_count    <= "100";                 -- 4
            when others =>                           -- "010" 第二关 · 向下箭头；
                                                     -- 其余编码（含胜负态的 "011"/"100"）
                o_rel_mask <= (L2B_P0, L2B_P1, L2B_P2, L2B_P3);  -- 也落进这套合法数据
                o_height   <= ("011", "011", "010", "001");
                o_width    <= ("011", "011", "010", "010");
                o_count    <= "100";                             -- 4
        end case;
    end process;

end architecture rtl;

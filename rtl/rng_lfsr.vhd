-- ============================================================
--  rng_lfsr —— 伪随机数发生器（8 位最大长度 LFSR）
--  所属子系统：S5 图案与随机数据（DWG-01）
--  职责：LFSR 伪随机数发生器
--  对应需求：提高要求③（零片初始位置随机）
--
--  【设计要点】
--   ① ⚠️ **绝不能复位成全 0** —— LFSR 的全 0 是吸收态，一旦进入就永远出不来。
--   ② ⚠️ **本模块不接任何节拍**，由 puzzle_ctrl 的 o_rnd_step 请求推进。
--      若改成"每个 tick 采一次"，则同一拍内的多次落位尝试读到同一个值
--      → 所有零片落点相同 → 必然重叠 → 每次都走回退布局。
--      **游戏照常能跑，只是永远不随机**，靠观察现象基本发现不了
--      （CLAUDE.md §10.1 / docs/02 §9.5）。
--   ③ 反馈抽头 = bit 7/5/4/3（Fibonacci 型，左移），
--      该抽头经穷举验证周期恰为 255（单环覆盖全部非零状态）。
--      实现只认抽头，不要按任何多项式名称反推抽头位置。
--   ④ 装载路径强制置 bit0：与 game_fsm 采样种子时的 or x"02" 构成双保险。
-- ============================================================

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;
use work.puzzle_pkg.ALL;

entity rng_lfsr is
    port (
        clk         : in  std_logic;
        rst         : in  std_logic;
        i_step      : in  std_logic;                     -- 推进一步（单周期脉冲）
        i_seed_load : in  std_logic;                     -- 装入种子
        i_seed      : in  std_logic_vector(7 downto 0);  -- 种子值（必须非零）
        o_rnd       : out std_logic_vector(7 downto 0)   -- 当前随机数
    );
end entity rng_lfsr;

architecture rtl of rng_lfsr is

    signal r_lfsr : std_logic_vector(7 downto 0);   -- 全模块唯一的状态，8 个触发器
    signal s_fb   : std_logic;                      -- 组合反馈

begin

    -- 反馈 = bit7 xor bit5 xor bit4 xor bit3（★ 抽头以本行为准）
    s_fb <= r_lfsr(7) xor r_lfsr(5) xor r_lfsr(4) xor r_lfsr(3);

    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_lfsr <= SEED_DEFAULT;             -- ★ 不能复位成全 0
            elsif i_seed_load = '1' then
                -- ★ 防御性置 bit0：万一上游送来 x"00"，这里也把状态按回非零
                --   （只多一根线，零额外逻辑）。上游 game_fsm 还有一道防线。
                r_lfsr <= i_seed or x"01";
            elsif i_step = '1' then
                r_lfsr <= r_lfsr(6 downto 0) & s_fb;   -- 左移 + 反馈进 bit0
            end if;
        end if;
    end process;

    o_rnd <= r_lfsr;                                -- 组合输出，不额外寄存

end architecture rtl;

-- ============================================================
--  clk_gen —— 时钟分频与复位产生
--  所属子系统：S1 时钟与节拍（DWG-01）
--  职责：时钟分频、节拍使能、复位产生（上电复位 ＋ 按键复位）
--  对应需求：1（SW7 门控与自检）、4（预览倒计时）、5（拼图倒计时）
--
--  【设计要点】
--   ① 输出的是**单周期使能脉冲**，不是分频时钟 —— 不驱动任何触发器的时钟端，
--      全设计仍是单时钟域（docs/01 §1.3）。
--   ② 5 级**串行级联**：只有第 1 级面对 50MHz，其余各级只数"上一级来了几个脉冲"。
--      并行方案（加 range）需 99 位，级联只要 33 位（CLAUDE.md §10.2 ②）。
--   ③ 复位是**三源或**：按键（课件 PDF p45 强制）＋ 上电 ＋ SW7 关断。
--      全项目只有本模块产生复位，其余 10 个实体都只收 o_rst。
-- ============================================================

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;
use work.puzzle_pkg.ALL;

entity clk_gen is
    port (
        clk        : in  std_logic;   -- 50MHz 系统时钟
        sys_en     : in  std_logic;   -- SW7 系统开关，高 = 开
        i_btn_rst  : in  std_logic;   -- BTN0 复位键，按下 = 1（课件 PDF p45（一））
        o_rst      : out std_logic;   -- 同步高有效复位（三源或）
        o_tick_8k  : out std_logic;   -- 8kHz 单周期使能
        o_tick_1k  : out std_logic;   -- 1kHz 单周期使能
        o_tick_100 : out std_logic;   -- 100Hz 单周期使能
        o_tick_2hz : out std_logic;   -- 2Hz 单周期使能
        o_tick_1hz : out std_logic    -- 1Hz 单周期使能
    );
end entity clk_gen;

architecture rtl of clk_gen is

    -- ---------- 分频计数器（全部带 range，见 CLAUDE.md §10.2 ①）----------
    -- ★ 6 个 CNT_* 常量在 puzzle_pkg 中单点定义，本模块只声明计数器。
    signal r_div_8k  : integer range 0 to CNT_8K;       -- 0~6249，13 位
    signal r_div_1k  : integer range 0 to CNT_1K;       -- 0~7，   3 位
    signal r_div_100 : integer range 0 to CNT_100;      -- 0~9，   4 位
    signal r_div_2hz : integer range 0 to CNT_2HZ;      -- 0~49，  6 位
    signal r_div_1hz : integer range 0 to CNT_1HZ;      -- 0~99，  7 位

    signal r_tick_8k  : std_logic;
    signal r_tick_1k  : std_logic;
    signal r_tick_100 : std_logic;
    signal r_tick_2hz : std_logic;
    signal r_tick_1hz : std_logic;

    -- ---------- 上电复位计数器 ----------
    --   ★ 数的是 r_tick_1k（1ms/拍），不是 clk：19 位 → 4 位，省约 25 个 LE
    signal r_por_cnt : integer range 0 to T_POR_MS-1;    -- 0~9，4 位
    signal r_por_rst : std_logic;

    -- ---------- 按键复位通路（2 级同步器 + 20ms 消抖）----------
    signal r_btn_s0  : std_logic;                       -- 同步器第 1 级
    signal r_btn_s1  : std_logic;                       -- 同步器第 2 级
    signal r_btn_cnt : integer range 0 to DEBOUNCE_BTN; -- 0~19，5 位
    signal r_btn_rst : std_logic;

begin

    -- ============================================================
    -- 第 1 级：唯一直接面对 50MHz 的计数器
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            r_tick_8k <= '0';                    -- 默认拉低
            if r_div_8k = CNT_8K then
                r_div_8k  <= 0;
                r_tick_8k <= '1';                -- 只高 1 个时钟周期
            else
                r_div_8k  <= r_div_8k + 1;
            end if;
        end if;
    end process;

    -- ============================================================
    -- 第 2~5 级：结构完全同构，只是使能来自上一级的 tick
    -- ============================================================
    -- 8kHz → 1kHz（分频比 8）
    process (clk)
    begin
        if rising_edge(clk) then
            r_tick_1k <= '0';
            if r_tick_8k = '1' then              -- ★ 使能来自上一级，不是 clk
                if r_div_1k = CNT_1K then
                    r_div_1k  <= 0;
                    r_tick_1k <= '1';
                else
                    r_div_1k  <= r_div_1k + 1;
                end if;
            end if;
        end if;
    end process;

    -- 1kHz → 100Hz（分频比 10）
    process (clk)
    begin
        if rising_edge(clk) then
            r_tick_100 <= '0';
            if r_tick_1k = '1' then
                if r_div_100 = CNT_100 then
                    r_div_100  <= 0;
                    r_tick_100 <= '1';
                else
                    r_div_100  <= r_div_100 + 1;
                end if;
            end if;
        end if;
    end process;

    -- 100Hz → 2Hz（分频比 50）：用于开机自检的 2 秒计时
    process (clk)
    begin
        if rising_edge(clk) then
            r_tick_2hz <= '0';
            if r_tick_100 = '1' then
                if r_div_2hz = CNT_2HZ then
                    r_div_2hz  <= 0;
                    r_tick_2hz <= '1';
                else
                    r_div_2hz  <= r_div_2hz + 1;
                end if;
            end if;
        end if;
    end process;

    -- 100Hz → 1Hz（分频比 100）：用于预览倒计时与拼图倒计时
    process (clk)
    begin
        if rising_edge(clk) then
            r_tick_1hz <= '0';
            if r_tick_100 = '1' then
                if r_div_1hz = CNT_1HZ then
                    r_div_1hz  <= 0;
                    r_tick_1hz <= '1';
                else
                    r_div_1hz  <= r_div_1hz + 1;
                end if;
            end if;
        end if;
    end process;

    -- ============================================================
    -- 上电复位：数满 T_POR_MS 个 tick_1k（= 10ms）后释放，期间输出高
    --   ※ 本进程**不得以 o_rst 为条件** —— 若写成"o_rst 有效时停止计数"，
    --      就永远退不出复位（docs/02 §3.5）。
    --   ※ 直数 clk 需要 19 位计数器（CNT_POR = 499999），而 EPM1270 只有
    --      1270 个 LE —— 改数 tick_1k 后只要 4 位。tick_1k 来自本模块的
    --      级联分频链，该链不依赖复位、上电即自由运行，所以此改动是安全的。
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if r_por_cnt = T_POR_MS-1 then
                r_por_rst <= '0';            -- 计满后释放，且不再回到 '1'
            else
                r_por_rst <= '1';            -- ★ 默认保持复位：上电后第一个时钟沿就断言
                if r_tick_1k = '1' then
                    r_por_cnt <= r_por_cnt + 1;
                end if;
            end if;
        end if;
    end process;

    -- ============================================================
    -- 按键复位（课件 PDF p45（一）"复位必须用按键来实现"
    --                ＋ p54「按键要注意防抖处理」）
    --   两级处理缺一不可：
    --     ① 2 级同步器：按键对 clk 是异步输入，直接采样会引入亚稳态
    --        （功能仿真查不出、上板偶发）；
    --     ② 20ms 消抖：时基直接取本模块已有的 r_tick_1k（1ms/拍），数 20 拍即得。
    --   ※ 本进程不得以 o_rst 为条件 —— 与上电复位计数器同一个坑。
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            -- ① 两级同步：把异步的按键收进 clk 域
            r_btn_s0 <= i_btn_rst;
            r_btn_s1 <= r_btn_s0;

            -- ② 消抖 20ms：数 r_tick_1k（1ms/拍）
            if r_btn_s1 = '0' then
                r_btn_cnt <= 0;                  -- 松开：立即清零、立即释放
                r_btn_rst <= '0';
            elsif r_tick_1k = '1' then
                if r_btn_cnt = DEBOUNCE_BTN then
                    r_btn_rst <= '1';            -- 稳定按住 20ms 才认定
                else
                    r_btn_cnt <= r_btn_cnt + 1;
                end if;
            end if;
        end if;
    end process;

    -- ============================================================
    -- 三源合并 + 输出接线
    -- ============================================================
    o_rst <= r_btn_rst or r_por_rst or (not sys_en);

    o_tick_8k  <= r_tick_8k;
    o_tick_1k  <= r_tick_1k;
    o_tick_100 <= r_tick_100;
    o_tick_2hz <= r_tick_2hz;
    o_tick_1hz <= r_tick_1hz;

end architecture rtl;

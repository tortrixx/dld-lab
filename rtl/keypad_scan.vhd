-- ============================================================
--  keypad_scan —— 4×4 矩阵键盘扫描与消抖
--  所属子系统：S2 键盘输入（DWG-01）
--  职责：4×4 矩阵键盘扫描、消抖、边沿检测
--  对应需求：6（选择）、7（移动）、8（确认）、9（判定）
--
--  【设计要点】
--   ① 本模块是**纯器件驱动**：只回答"按了哪个键"（键号 1~16），
--      不认识"上下左右" —— 布局 → 动作的译码属于游戏规则，在 game_fsm。
--   ② 消抖计的是"扫描轮次"（一轮 = 4 个 i_tick = 4ms），
--      必须先把 4 相锁存成"轮键号"再做整轮判定（docs/02 §4.4）。
--   ③ o_key_press 是**单周期脉冲（宽度 1 个 clk）** —— 跨模块契约
--      （CLAUDE.md §10.1）。
--   ④ 键号 = (3 - ROW) * 4 + COL + 1；实物 ROW3 在最上排。
--      o_key_code 必须是 **5 位**（最大键号 16，4 位装不下会被静默截断成 0）。
-- ============================================================

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;
use work.puzzle_pkg.ALL;

entity keypad_scan is
    port (
        clk         : in  std_logic;
        rst         : in  std_logic;
        i_tick      : in  std_logic;                    -- 1kHz（扫描 + 消抖计时）
        i_kp_row    : in  std_logic_vector(3 downto 0); -- 行输入，按下 = '0'（低有效，见 KP_ACTIVE）
        o_kp_col    : out std_logic_vector(3 downto 0); -- 列扫描，选中列驱 '0'、其余驱 '1'
        o_key_code  : out std_logic_vector(4 downto 0); -- 键号 1~16；0 = 无键
        o_key_press : out std_logic                     -- 单次按下脉冲，宽 1 个 clk
    );
end entity keypad_scan;

architecture rtl of keypad_scan is

    -- ============================================================
    -- ★ 键盘扫描极性 —— 全项目**唯一的极性翻转点**
    --   KP_ACTIVE = '0' → **低有效**：选中列驱 '0'、其余驱 '1'；
    --                    按下时该键把选中列的低电平接到行上，**行读到 '0' 即"按下"**。
    --   KP_ACTIVE = '1' → 高有效：选中列驱 '1'，行读到 '1' 即"按下"。
    --
    --   ※ 为什么低有效对两种板子都成立（本方案被选中的理由）：
    --     · 行外接**下拉** → 无键时行 = 0；按下时选中列的低电平仍把行压成 0
    --       → 靠"选中列是低、其余列是高"区分：读 0 = 按下 √
    --     · 行外接**上拉** → 无键时行 = 1；按下时被选中列拉低 → 读 0 = 按下 √
    --
    --   ※ 2026-09-24 上板实测订正（ERRORS.md ERR-0035）：
    --     原按**开发板手册**写成高有效（驱列为高、读 1 = 按下）。
    --     实测发现**行在无按键时就一直读到 '1'** → 每一相都误报按键 →
    --     键号随相号循环 1→2→3→4，其中 **4 = 「开始」** →
    --     触发 game_fsm 的全局边「任意状态按开始 → S_PREVIEW」→
    --     系统被踢出自检态、直接进预览（现场表现为"没有 2 秒自检、直接 5 秒计时"）。
    --     → 改为课程课件 PDF p55 的**低有效**方案（docs/04 §3.3 早已记下这处两源矛盾）。
    -- ============================================================
    constant KP_ACTIVE : std_logic := '0';

    -- 扫描相推进（★ r_phase 必须是 unsigned：裸 std_logic_vector 没有 +1）
    signal r_phase : unsigned(1 downto 0);

    -- 一轮 = 4 个相；r_round_key 把"本轮任一相读到的键"锁存到整轮结束
    signal r_round_key : integer range 0 to 16;   -- 本轮读到的键号（0 = 整轮无键）
    signal r_stable    : integer range 0 to 16;   -- 消抖后的稳定键号（0 = 无键）
    signal r_cnt       : integer range 0 to DEBOUNCE_MAX;  -- ★ 数"轮"
    signal r_down      : std_logic;               -- ★ 内部闸门，不是端口

begin

    -- ============================================================
    -- 扫描相推进：4 个 i_tick 完成一轮（0→1→2→3→0 自然回绕）
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_phase <= (others => '0');
            elsif i_tick = '1' then
                r_phase <= r_phase + 1;
            end if;
        end if;
    end process;

    -- 列输出：一次只驱动一列（1 sll phase 综合成译码器）
    --   KP_ACTIVE = '0'（低有效）→ 选中列驱低、其余驱高；= '1' → 选中列驱高。
    --   ★ 常量比较在综合期折叠，不额外耗 LE。
    o_kp_col <= not std_logic_vector(to_unsigned(1, 4) sll to_integer(r_phase))
                when KP_ACTIVE = '0'
                else std_logic_vector(to_unsigned(1, 4) sll to_integer(r_phase));

    -- ============================================================
    -- 消抖与边沿检测
    --   消抖的比较单位是"**一轮读到的键**"，不是"一相读到的键"：
    --   按住一个键时，一轮 4 个相里只有该键所在的那一相读到键号，
    --   其余 3 个相读到 0 —— 所以必须先把 4 相锁存成一个"轮键号"，
    --   整轮结束（相 3 → 相 0 的回绕点）再做一次判定。
    --   时长账：第 1 个轮末建立 r_stable（不计）、随后 19 个轮末累加、
    --   第 21 个轮末才出脉冲 → 从按下沿到脉冲沿 = 80~87ms。
    -- ============================================================
    process (clk)
        variable v_raw   : integer range 0 to 16;   -- 本相读到的原始键号
        variable v_round : integer range 0 to 16;   -- 含本相在内的本轮键号
    begin
        if rising_edge(clk) then
            -- ★ 每个 clk 都先清零 —— 这是"脉冲宽度恰好 1 个 clk"的实现要点。
            --   若写在 i_tick 分支内，信号在非 tick 拍会保持原值 → 脉冲宽 1ms。
            o_key_press <= '0';

            if rst = '1' then
                r_round_key <= 0;
                r_stable    <= 0;
                r_cnt       <= 0;
                r_down      <= '0';
            elsif i_tick = '1' then
                -- ① 读当前相的原始键号
                --    键号公式 KEY号 = (3-ROW)*4 + COL + 1（COL = 当前相号）
                --    同列多键时行号大者优先（循环里后赋值胜出，单键应用）
                v_raw := 0;
                for r in 0 to 3 loop
                    if i_kp_row(r) = KP_ACTIVE then
                        v_raw := (3 - r) * 4 + to_integer(r_phase) + 1;
                    end if;
                end loop;

                -- ② 本轮键号：任一相有键即覆盖（含本相）
                v_round := r_round_key;
                if v_raw /= 0 then
                    v_round := v_raw;
                end if;

                if r_phase = 3 then
                    -- ③ 整轮结束：用 v_round 做一次消抖判定
                    --    ※ 这里**不给 r_phase 赋值** —— 相推进由上面那个进程负责，
                    --       否则两处写同一信号 = 多重驱动（Quartus 报错）。
                    r_round_key <= 0;                     -- 新一轮从"无键"开始
                    if v_round = r_stable then
                        if r_cnt < DEBOUNCE_MAX then
                            r_cnt <= r_cnt + 1;           -- 连续读到同一键，累加一轮
                        else
                            -- 连续 20 轮一致 → 消抖完成
                            if r_stable /= 0 and r_down = '0' then
                                o_key_press <= '1';       -- 新按下 → 出一个脉冲
                            end if;
                            if r_stable /= 0 then
                                r_down <= '1';            -- 闸门：按住期间封门
                            else
                                r_down <= '0';            -- 整轮无键持续 20 轮 → 开门
                            end if;
                        end if;
                    else
                        r_stable <= v_round;              -- 轮键号变了，重新计数
                        r_cnt    <= 0;
                    end if;
                else
                    r_round_key <= v_round;               -- 本轮继续累积
                end if;
            end if;
        end if;
    end process;

    -- ★ 稳定键号在端口边界转一次：
    --   下游用 "o_key_code /= 0" 判"有没有键按住"（不再单出 o_key_down 端口）
    o_key_code <= std_logic_vector(to_unsigned(r_stable, 5));

end architecture rtl;

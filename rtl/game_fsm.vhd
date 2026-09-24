-- ============================================================
--  game_fsm —— 时间调度器（主状态机）
--  所属子系统：S3 游戏控制（DWG-01）
--  职责：游戏主状态机、倒计时、关卡切换、图案与音效选择
--  对应需求：1（开机自检）、2（待机）、3（关卡号）、4（预览 5 秒）、
--            5（限时 30 秒）、9/10（判定与第二关）、11（任意状态重开）、
--            提高要求②（多图案随机）、提高要求①（音效选择）
--
--  ※ 本模块**只管时间**：完全不做坐标运算、不碰掩码。
--
--  【状态机分类（答辩必问，课件 p30~p32）】
--   · 输出类型：**Moore 型**（带两处 Mealy 例外：o_sel_out / o_conf_out
--     由输入 i_key_press 直接组合产生）；
--   · 进程描述方式：**双进程 · 形式 2** —— 进程 1（本模块的主时钟进程）
--     描述次态逻辑 + 状态寄存器；进程 2（输出逻辑）用并行条件赋值实现
--     （o_pattern_sel / o_sel_out / o_conf_out）。
--   · 为什么不用三进程：三进程要多一根次态信号、多一处"忘赋值"的隐患；
--     为什么不用单进程：单进程要把输出也塞进唯一的时钟进程，仿真时
--     "状态跳变 <-> 显示"的因果关系看不出来，而评分项③要的就是波形可判读。
--
--  【两条"任意状态"边】
--   · 复位：任意状态 → S_SELF_TEST（rst = 按键 或 上电 或 SW7 关断）
--   · 重开：任意状态按「开始」→ **直接进 S_PREVIEW**（不是先回 S_IDLE），
--     依据是要求 11 的验收判据原文"均能立即回到第一关的预览态"。
-- ============================================================

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;
use work.puzzle_pkg.ALL;

entity game_fsm is
    port (
        clk            : in  std_logic;
        rst            : in  std_logic;

        -- ---- 节拍 ----
        i_tick_1hz     : in  std_logic;   -- 倒计时
        i_tick_2hz     : in  std_logic;   -- 开机自检 2 秒计时
        i_tick_100     : in  std_logic;   -- 方向键连发计时 + o_blink 分频基准

        -- ---- 来自 S2 键盘输入（原始键号，译码在本模块内做）----
        i_key_code     : in  std_logic_vector(4 downto 0);  -- 键号 1~16；0 = 无键
        i_key_press    : in  std_logic;                     -- 单次按下脉冲（1 个 clk）

        -- ---- 来自 S4 拼图核心 ----
        i_all_locked   : in  std_logic;
        i_solved       : in  std_logic;

        -- ---- 输出 ----
        o_state        : out std_logic_vector(2 downto 0);
        o_blink        : out std_logic;                     -- 2Hz 方波（自检闪烁）
        o_level        : out std_logic;
        o_preview_cnt  : out std_logic_vector(2 downto 0);
        o_game_cnt_bcd : out std_logic_vector(7 downto 0);  -- BCD：(7..4) 十位,(3..0) 个位
        o_pattern_sel  : out std_logic_vector(2 downto 0);
        o_round_start  : out std_logic;                     -- 新一局脉冲（1 个 clk）
        o_sel_out      : out std_logic;
        o_conf_out     : out std_logic;
        o_dir_out      : out std_logic_vector(3 downto 0);
        o_sound_sel    : out std_logic_vector(2 downto 0);
        o_sound_trig   : out std_logic;                     -- 音效触发脉冲（1 个 clk）
        o_seed_load    : out std_logic;
        o_seed         : out std_logic_vector(7 downto 0)
    );
end entity game_fsm;

architecture rtl of game_fsm is

    -- ============================================================
    -- 全部寄存器（共 46 个触发器，全部带 range 或明确位宽）
    -- ============================================================
    -- 状态与关卡
    signal r_state       : state_t;                          -- 3 位
    signal r_level       : std_logic;                        -- 1 位

    -- 倒计时（全部 BCD，见 docs/02 §11.4：省掉除法器）
    signal r_preview_cnt : std_logic_vector(2 downto 0);     -- 3 位，预览只数到 5
    signal r_pv_load     : std_logic;                        -- 1 位：预览倒计时装载请求
    signal r_cnt_tens    : unsigned(3 downto 0);             -- 4 位 BCD 十位（0~4）
    signal r_cnt_ones    : unsigned(3 downto 0);             -- 4 位 BCD 个位（0~9）
    signal r_cnt_load    : std_logic;                        -- 1 位：拼图倒计时装载请求

    -- 随机源
    signal r_free        : unsigned(7 downto 0);             -- 8 位自由运行计数器
                                                             -- （unsigned：要 +1）
    signal r_seed        : std_logic_vector(7 downto 0);     -- 8 位，按"开始"时采样
    signal r_seed_load   : std_logic;                        -- 1 位：种子装载脉冲

    -- 闪烁方波（要求 1 的自检闪烁）
    signal r_blink_div   : integer range 0 to CNT_BLINK;     -- 5 位，100Hz ÷ 25 = 4Hz
    signal r_blink       : std_logic;                        -- 1 位，每 4Hz 翻转 → 2Hz 方波

    -- 连发
    signal r_repeat_cnt  : integer range 0 to REPEAT_DELAY;  -- 3 位

    -- 自检计时（要求 1）
    signal r_self_cnt    : integer range 0 to 2*T_SELFTEST - 1;  -- 0~3，计 4 拍 tick_2hz = 2 秒

    -- 方向键脉冲（内部信号，供音效进程读；out 端口在 VHDL-93 里不可读）
    signal r_dir_out     : std_logic_vector(3 downto 0);
    signal r_keypress_1  : std_logic;                        -- FIX 2026-09-24 (ERR-0040): delay flag to suppress move-sound on cycle after keypress

    -- 图案选择（寄存输出，见 (12) 的说明）
    signal r_pattern_sel : std_logic_vector(2 downto 0);

    -- 键号译码结果（必须是信号：多个进程都要引用）
    signal s_act_up      : std_logic;
    signal s_act_start   : std_logic;
    signal s_act_left    : std_logic;
    signal s_act_down    : std_logic;
    signal s_act_right   : std_logic;
    signal s_act_sel     : std_logic;
    signal s_act_conf    : std_logic;
    signal s_dir_code    : std_logic_vector(3 downto 0);     -- 方向独热码
    signal s_is_dir      : std_logic;                        -- 当前按键是不是方向键

    -- 供音效进程复用的判定条件（与主状态进程的迁移条件逐条一致）
    signal s_win_now     : std_logic;
    signal s_fail_now    : std_logic;

begin

    -- ============================================================
    -- ① 自由运行计数器（除 rst 外从不停止，每 clk 加 1）
    --    用途：按下「开始」时采样一次当随机种子。
    --    为什么不用 rng_lfsr.o_rnd 当种子：那个只在 puzzle_ctrl 请求时步进，
    --    复位后的值本身由种子决定 —— 拿它的输出当种子是循环论证。
    --    自由运行计数器与采样时刻无关：采到哪个值完全取决于人按「开始」的时机。
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_free <= (others => '0');
            else
                r_free <= r_free + 1;            -- ★ 无条件自增，没有使能
            end if;
        end if;
    end process;

    -- ============================================================
    -- ② 键号译码（游戏规则的一部分，只写在这一个进程里）
    --    keypad_scan 只回答"按了哪个键"，"这个键意味着什么"由本模块回答。
    --    ※ 选择表达式是 5 位，每个 choice 必须也是 5 位。
    -- ============================================================
    process (i_key_code)
    begin
        -- 默认值先行，防 latch
        s_act_up    <= '0';  s_act_start <= '0';
        s_act_left  <= '0';  s_act_down  <= '0';
        s_act_right <= '0';  s_act_sel   <= '0';
        s_act_conf  <= '0';
        case i_key_code is
            when "00010" => s_act_up    <= '1';   -- 键 2  上   （ROW3·COL1）
            when "00100" => s_act_start <= '1';   -- 键 4  开始 （ROW3·COL3）
            when "00101" => s_act_left  <= '1';   -- 键 5  左   （ROW2·COL0）
            when "00110" => s_act_down  <= '1';   -- 键 6  下   （ROW2·COL1）
            when "00111" => s_act_right <= '1';   -- 键 7  右   （ROW2·COL2）
            when "01000" => s_act_sel   <= '1';   -- 键 8  选择 （ROW2·COL3）
            when "01100" => s_act_conf  <= '1';   -- 键 12 确认 （ROW1·COL3）
            when others  => null;                 -- 空白键位与"无键"都不产生动作
        end case;
    end process;

    -- 上/下/左/右 → 4 位独热，与 puzzle_ctrl.i_dir 的编码一致
    s_dir_code <= s_act_up & s_act_down & s_act_left & s_act_right;
    s_is_dir   <= s_act_up or s_act_down or s_act_left or s_act_right;

    -- ★ "选择" / "确认"脉冲转发：只在 S_PLAYING 转发
    --    （这两处是本状态机仅有的 **Mealy 成分**：由输入直接组合产生）
    o_sel_out  <= '1' when (i_key_press = '1' and s_act_sel  = '1' and r_state = S_PLAYING)
                  else '0';
    o_conf_out <= '1' when (i_key_press = '1' and s_act_conf = '1' and r_state = S_PLAYING)
                  else '0';

    -- ============================================================
    -- ③ 种子采样：按「开始」那一拍把自由运行计数器的当前值锁进 r_seed
    --    ★ 防全零但不能固定某一位：LFSR 全 0 是吸收态，这里置 bit1
    --      （不是 bit0 —— bit0 被 o_pattern_sel 用来在两种箭头间二选一，
    --       若把 bit0 恒置 1，"向上箭头"就永远选不到，提高要求②静默失效）。
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_seed      <= (others => '0');
                r_seed_load <= '0';
            else
                r_seed_load <= '0';              -- 默认：装载脉冲只有一拍
                if i_key_press = '1' and s_act_start = '1' then
                    r_seed      <= std_logic_vector(r_free) or x"02";  -- ★ 保证非零，且所有位仍然随机
                    r_seed_load <= '1';
                end if;
            end if;
        end if;
    end process;

    o_seed      <= r_seed;
    o_seed_load <= r_seed_load;

    -- ============================================================
    -- ④ 闪烁方波：i_tick_100 ÷ 25 得 4Hz，再翻转得 **2Hz 方波**（占空比 50%）
    --    ※ 不能把 i_tick_2hz 直接当方波送出去：本项目所有 tick
    --       都是**单周期使能**（一拍宽），把它当方波得到的是 1Hz。
    --    ※ 用"翻转"而不是"数到一半置 1"：只花 1 个触发器表达状态本身。
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_blink_div <= 0;
                r_blink     <= '0';
            elsif i_tick_100 = '1' then
                if r_blink_div = CNT_BLINK then      -- 0~CNT_BLINK 共 25 个数
                    r_blink_div <= 0;
                    r_blink     <= not r_blink;
                else
                    r_blink_div <= r_blink_div + 1;
                end if;
            end if;
        end if;
    end process;

    o_blink <= r_blink;

    -- ============================================================
    -- ⑤ 主状态机（进程 1：次态逻辑 + 状态寄存器）
    --    迁移图见 docs/图/系统图.html 的 DWG-03，逐条对应。
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_state       <= S_SELF_TEST;
                r_level       <= '0';
                r_self_cnt    <= 0;
                r_pv_load     <= '0';
                r_cnt_load    <= '0';
                o_round_start <= '0';
            else
                -- 默认值（脉冲类信号一律"每拍先清、只在迁移拍置位"）
                r_pv_load     <= '0';
                r_cnt_load    <= '0';
                o_round_start <= '0';

                if i_key_press = '1' and s_act_start = '1' then
                    -- ★ 【全局边】任意 6 个状态按「开始」→ 直接回第一关预览（要求 11）
                    --    不经过 S_IDLE：走中转的话按一次只会停在待机态，
                    --    要按两次才回到预览，与验收判据"立即回到第一关的预览态"不符。
                    r_state       <= S_PREVIEW;
                    r_level       <= '0';
                    r_pv_load     <= '1';        -- 预览倒计时 ← 5
                    o_round_start <= '1';        -- 通知 puzzle_ctrl 重新随机散落
                    r_self_cnt    <= 0;
                else
                    case r_state is

                        -- ---- 开机自检：点亮 2 秒（tick_2hz 数 4 拍）----
                        when S_SELF_TEST =>
                            if i_tick_2hz = '1' then
                                if r_self_cnt = 2*T_SELFTEST - 1 then
                                    r_state    <= S_IDLE;
                                    r_self_cnt <= 0;
                                else
                                    r_self_cnt <= r_self_cnt + 1;
                                end if;
                            end if;

                        -- ---- 待机：等「开始」键（由上面的全局边处理）----
                        when S_IDLE =>
                            null;

                        -- ---- 图案预览：5 秒倒计时 ----
                        -- 减到 1 的那一拍同拍搬到 S_PLAYING（既不是"显示完 0 再迁移"、
                        -- 也不额外多等一拍）→ S_PREVIEW 恰好 5 秒，DISP7 不显示 0
                        when S_PREVIEW =>
                            if i_tick_1hz = '1' and unsigned(r_preview_cnt) <= 1 then
                                r_state    <= S_PLAYING;
                                r_cnt_load <= '1';   -- 倒计时装载 30 / 40
                            end if;

                        -- ---- 拼图中：三条出口 ----
                        when S_PLAYING =>
                            if i_all_locked = '1' then
                                if i_solved = '1' then
                                    -- ① 全锁且拼对
                                    if r_level = '0' then
                                        r_level       <= '1';        -- 进第二关
                                        r_state       <= S_PREVIEW;  -- 再看一遍图案
                                        r_pv_load     <= '1';
                                        o_round_start <= '1';        -- 第二关重新散落
                                    else
                                        r_state <= S_WIN;            -- 第二关通过 → 胜利
                                    end if;
                                else
                                    -- ② 全锁但没拼对 → 立即判失败（不等倒计时耗尽）
                                    r_state <= S_FAIL;
                                end if;
                            elsif i_tick_1hz = '1' and
                                  (r_cnt_tens = 0) and (r_cnt_ones = 1) then
                                -- ③ 倒计时走到最后一秒（下一拍归零）→ 超时失败。
                                --    这样判失败正好发生在第 30/40 秒，不多给一秒。
                                r_state <= S_FAIL;
                            end if;

                        -- ---- 胜负已分：等「开始」重开（由全局边处理）----
                        when others =>              -- S_WIN / S_FAIL
                            null;

                    end case;
                end if;
            end if;
        end if;
    end process;

    -- ============================================================
    -- ⑥ 预览倒计时（3 位二进制）
    --    ★ 装载与递减在**同一个进程**内，一个信号只有一个写者
    --      （装载请求 r_pv_load 由状态进程发，1 个 clk 宽）。
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_preview_cnt <= (others => '0');
            elsif r_pv_load = '1' then
                r_preview_cnt <= std_logic_vector(to_unsigned(T_PREVIEW, 3));
            elsif r_state = S_PREVIEW and i_tick_1hz = '1' and
                  unsigned(r_preview_cnt) /= 0 then
                r_preview_cnt <= std_logic_vector(unsigned(r_preview_cnt) - 1);
            end if;
        end if;
    end process;

    -- ============================================================
    -- ⑦ 拼图倒计时（两位 BCD）
    --    ★ 装载与递减同样在同一个进程内（r_cnt_load 由状态进程发）。
    --    ※ r_cnt_tens = 0 且 r_cnt_ones = 0 时必须**保持不变**，
    --       否则会从 00 回绕到 99（本项目三处"无符号减法回绕"陷阱之一）。
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_cnt_tens <= (others => '0');
                r_cnt_ones <= (others => '0');
            elsif r_cnt_load = '1' then
                -- ★ 按当前关卡选 30 / 40；除以 10 是**常量表达式**，
                --   在 elaboration 阶段就被折叠成字面量，不产生除法器。
                if r_level = '0' then
                    r_cnt_tens <= to_unsigned(T_LEVEL1 / 10, 4);
                    r_cnt_ones <= to_unsigned(T_LEVEL1 mod 10, 4);
                else
                    r_cnt_tens <= to_unsigned(T_LEVEL2 / 10, 4);
                    r_cnt_ones <= to_unsigned(T_LEVEL2 mod 10, 4);
                end if;
            elsif r_state = S_PLAYING and i_tick_1hz = '1' then
                if r_cnt_ones = 0 then
                    if r_cnt_tens = 0 then
                        null;                        -- 已到 0，保持不变
                    else
                        r_cnt_tens <= r_cnt_tens - 1;   -- 借位
                        r_cnt_ones <= to_unsigned(9, 4);
                    end if;
                else
                    r_cnt_ones <= r_cnt_ones - 1;
                end if;
            end if;
        end if;
    end process;

    -- ============================================================
    -- ⑧ 方向键连发计时（★ r_repeat_cnt 的**唯一写者**就是这个进程）
    --    行为：按下的那一拍立即响应一次，之后"按住 500ms → 每 100ms 重复一次"
    --    ★ 重置必须放在 i_tick_100 闸门**外**：i_key_press 是 1 个 clk 宽的脉冲，
    --      与每 10ms 才出现一拍的 i_tick_100 基本不可能同拍；写在闸门内的话
    --      重置形同废弃（计数器从上次的值继续递减，"按住 500ms 才开始连发"名存实亡）。
    --    ★ 到期后重新装载 REPEAT_PERIOD（=1 拍）而不是清零：清零会让"每 100ms 一次"
    --      再也回不到 1（判据要求 = 1），连发只出一次就停了。
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_repeat_cnt <= REPEAT_DELAY;
            elsif i_key_press = '1' and s_is_dir = '1' then
                r_repeat_cnt <= REPEAT_DELAY;              -- 新按下：立刻重置为 500ms
            elsif i_tick_100 = '1' and s_is_dir = '1' then
                if r_repeat_cnt > 1 then
                    r_repeat_cnt <= r_repeat_cnt - 1;      -- 还按着：每 100ms 减 1
                else
                    r_repeat_cnt <= REPEAT_PERIOD;         -- 到期 → 重新装载连发周期
                end if;
            end if;
        end if;
    end process;

    -- ============================================================
    -- ⑨ 方向脉冲输出（寄存、每拍先清零 → 保证是脉冲）
    --    首次连发发生在 r_repeat_cnt 减到 1 的那一拍（即按住 500ms 时）；
    --    它只**读** r_repeat_cnt，不写 —— 否则就是多重驱动（课件 p58）。
    --    只在 S_PLAYING 生效（其他状态下按方向键无效果）。
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_dir_out <= "0000";
            elsif r_state /= S_PLAYING then
                r_dir_out <= "0000";                       -- 非拼图状态：方向键无效
            else
                r_dir_out <= "0000";                       -- 默认每拍清零（保证是脉冲）
                if i_key_press = '1' and s_is_dir = '1' then
                    r_dir_out <= s_dir_code;               -- 首次：立即响应
                elsif i_tick_100 = '1' and s_is_dir = '1' and r_repeat_cnt = 1 then
                    r_dir_out <= s_dir_code;               -- 连发：每 100ms 一次
                end if;
            end if;
        end if;
    end process;

    o_dir_out <= r_dir_out;

    -- ============================================================
    -- ⑩ 音效触发与选择（提高要求①）
    --    触发点逐条对应 docs/02 §12.7A 的表；o_sound_trig 一律是**单周期脉冲**，
    --    o_sound_sel 是电平（buzzer_ctrl 在 i_trigger 那一拍把它锁存）。
    -- ============================================================
    -- 与主状态进程的迁移条件逐条一致（同拍求值，故触发沿与状态迁移同拍）
    s_win_now  <= '1' when (r_state = S_PLAYING and i_all_locked = '1' and
                            i_solved = '1' and r_level = '1') else '0';
    s_fail_now <= '1' when (r_state = S_PLAYING and
                            ((i_all_locked = '1' and i_solved = '0') or
                             (i_all_locked = '0' and i_tick_1hz = '1' and
                              r_cnt_tens = 0 and r_cnt_ones = 1))) else '0';

    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                o_sound_trig <= '0';
                o_sound_sel  <= "000";
            else
                o_sound_trig <= '0';                       -- 默认：脉冲只有一拍
                r_keypress_1 <= i_key_press;                 -- FIX 2026-09-24 (ERR-0040): record previous keypress for move-sound gating
                if s_win_now = '1' then
                    o_sound_sel  <= "110";                 -- 成功
                    o_sound_trig <= '1';
                elsif s_fail_now = '1' then
                    o_sound_sel  <= "111";                 -- 失败
                    o_sound_trig <= '1';
                elsif i_key_press = '1' and s_act_conf = '1' and r_state = S_PLAYING then
                    o_sound_sel  <= "011";                 -- 锁定
                    o_sound_trig <= '1';
                elsif i_key_press = '1' and
                      (s_act_up = '1' or s_act_down = '1' or s_act_left = '1' or
                       s_act_right = '1' or s_act_start = '1' or
                       s_act_sel = '1' or s_act_conf = '1') then
                    o_sound_sel  <= "001";                 -- 按键
                    o_sound_trig <= '1';
                elsif r_dir_out /= "0000" and r_keypress_1 = '0' then
                    -- FIX 2026-09-24 (ERR-0040): gate move-sound with r_keypress_1.
                    --    r_dir_out is cleared every cycle, but sound process sees
                    --    previous cycle value (delayed by 1 clk). On cycle after
                    --    keypress, r_dir_out still looks non-zero -> false move-sound.
                    --    r_keypress_1='1' suppresses it; '0' allows burst-repeat sound.
                    o_sound_sel  <= "010";                 -- 移动（含连发）
                    o_sound_trig <= '1';
                elsif r_state = S_PREVIEW and i_tick_1hz = '1' and
                      unsigned(r_preview_cnt) /= 0 then
                    o_sound_sel  <= "100";                 -- 预览倒计时每秒
                    o_sound_trig <= '1';
                elsif r_state = S_PLAYING and i_tick_1hz = '1' and
                      (r_cnt_tens = 0) and (r_cnt_ones >= 1) and (r_cnt_ones <= 5) then
                    o_sound_sel  <= "101";                 -- 拼图倒计时最后 5 秒
                    o_sound_trig <= '1';
                end if;
            end if;
        end if;
    end process;

    -- ============================================================
    -- (11) 状态类输出的接线
    --    ※ o_game_cnt_bcd 的拼接顺序是**生产侧的契约**：十位在 (7..4)、
    --       个位在 (3..0)。写反了 DISP4/DISP3 就会显示互换（30 显示成 03），
    --       而 disp_format 自己的 TB 直接注入整字、天然查不出这个错。
    -- ============================================================
    o_state        <= r_state;
    o_level        <= r_level;
    o_preview_cnt  <= r_preview_cnt;
    o_game_cnt_bcd <= std_logic_vector(r_cnt_tens) & std_logic_vector(r_cnt_ones);

    -- ============================================================
    -- (12) 提高要求②：多图案随机（第二关在上箭头 / 下箭头里二选一）
    --    ※ 用**寄存输出**（时序分析实测：组合版会把
    --       r_state → o_pattern_sel → piece_rom → puzzle_ctrl 串成一条
    --       22ns 的长路径，Fmax 掉到 44MHz；寄存一级后这条路从寄存器起算）。
    --       代价是图案比状态变化晚 1 个 clk —— 散落序列器在 o_round_start 之后
    --       至少 2 拍才用到这些数据，完全来得及。
    --    ★ 状态优先：胜负态直接选对应图案（否则 "011"/"100" 永远不可达，
    --       胜负图案画不出来）。副作用见 docs/02 §12.6 的说明。
    --    ★ 第二关的选择取自开局种子 r_seed(0)：图案在按「开始」时就定了。
    --      注意：r_seed 的防全零置的是 bit1，**不能用 bit1 做选择位**。
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_pattern_sel <= "000";
            else
                if r_state = S_WIN then
                    r_pattern_sel <= "011";          -- 胜利图案
                elsif r_state = S_FAIL then
                    r_pattern_sel <= "100";          -- 失败图案
                elsif r_level = '0' then
                    r_pattern_sel <= "000";          -- 第一关：固定 4×3 矩形
                elsif r_seed(0) = '0' then
                    r_pattern_sel <= "001";          -- 第二关：向上箭头
                else
                    r_pattern_sel <= "010";          -- 第二关：向下箭头
                end if;
            end if;
        end if;
    end process;

    o_pattern_sel <= r_pattern_sel;

end architecture rtl;

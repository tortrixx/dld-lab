-- ============================================================
--  puzzle_ctrl —— 空间引擎（核心模块）
--  所属子系统：S4 拼图核心（DWG-01）
--  职责：零片锚点 / 选择 / 移动 / 钳位 / 锁定 / 正确性判定
--  对应需求：6（选择）、7（移动与边界）、8（锁定）、9（判定）
--
--  ※ 本模块**只管空间**：没有倒计时、没有秒概念、不知道第几关。
--     时间由 game_fsm 管 —— 这是本设计最核心的结构决策（docs/01 §1.2 原则一）。
--
--  【三条不变量】
--   ① 锚点不变量：任何时刻 行 + 高 ≤ 8 且 列 + 宽 ≤ 8
--      → 由散落钳位与移动钳位**主动保证**，"非法移动根本不发生"；
--   ② 掩码不存储：只存锚点 (row,col)，像素由**时分复用的行扫描引擎**算出
--      → 省 256 个触发器，且结构上杜绝"锚点与掩码不一致"；
--   ③ 并集即判定：o_solved = (4 块掩码的并集 == 目标掩码)
--      → 与铺法无关，自动接受全部合法解（第一关有 2 种合法铺法）。
--
--  ★【面积策略：为什么不是"4 路 place() 组合展开"】
--    文档原方案是把 4 块零片各展开一份 place() 平移逻辑（4×64 逐格搬运）。
--    实测（Quartus II 9.1 / EPM1270T144C5）该写法仅本模块就要 2587 个 LE，
--    而整片只有 1270 个，直接放不下。
--    现改为**时分复用**（CLAUDE.md §10.2 ④「共享运算资源」的正式用法）：
--      · 只有一套"行扫描引擎"：每拍算 1 块零片的 1 个输出行（8 位）；
--      · 4 块 × 8 行 = 32 拍刷新一帧（约 0.64μs @50MHz），点阵 500Hz 扫描看不出来；
--      · 引擎在**事件**（开局 / 散落落子 / 选择 / 移动 / 锁定）时启动一帧，
--        完成后静止 → 显示的是稳定整帧，不会撕裂。
--    代价：o_px_red / o_px_green 由"纯组合"变为**寄存输出**；
--    且 o_solved 在刷新期间（≤0.64μs）保持 '0'（这是必需的，见下面 ⑧ 的说明）。
--
--  ★【散落的重叠判定：用包围盒，不用掩码求交】
--    原方案"算候选位置的 64 位掩码再与已放置并集求交"，需要再造一份平移逻辑。
--    现改为**包围盒不相交**判据：
--        相交 当且仅当 (r1 < r2+h2) 且 (r2 < r1+h1) 且 (c1 < c2+w2) 且 (c2 < c1+w1)
--    这是**保守**判据（真实形状是不规则多联骨牌，包围盒不交一定不重叠），
--    所以**绝不会把重叠判成不重叠**；代价是偶尔拒绝一个本可放置的位置，
--    由"8 次尝试 + 回退表"兜住，随机性不受影响。且它只用整数比较，无掩码运算。
-- ============================================================

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;
use work.puzzle_pkg.ALL;

entity puzzle_ctrl is
    port (
        clk           : in  std_logic;
        rst           : in  std_logic;

        -- ---- 新一局 ----
        i_round_start : in  std_logic;   -- 新一局脉冲：清锁定、重新随机散落

        -- ---- 来自 S5 图案与随机数据 ----
        i_target_mask : in  std_logic_vector(63 downto 0);  -- 目标图案掩码
        i_rel_mask    : in  mask_arr_t;                     -- 4 块零片相对掩码
        i_height      : in  dim_arr_t;                      -- 4 块包围盒高
        i_width       : in  dim_arr_t;                      -- 4 块包围盒宽
        i_piece_count : in  std_logic_vector(2 downto 0);   -- 本关零片数 3 或 4
        i_rnd         : in  std_logic_vector(7 downto 0);   -- 随机数
        o_rnd_step    : out std_logic;                      -- 请求随机数前进一步

        -- ---- 来自 S3 游戏控制（转发来的操作键脉冲）----
        i_sel         : in  std_logic;                      -- "选择"键脉冲
        i_conf        : in  std_logic;                      -- "确认"键脉冲
        i_dir         : in  std_logic_vector(3 downto 0);   -- (3)上 (2)下 (1)左 (0)右

        -- ---- 输出 ----
        o_px_red      : out std_logic_vector(63 downto 0);  -- 点阵红色像素
        o_px_green    : out std_logic_vector(63 downto 0);  -- 点阵绿色像素
        o_all_locked  : out std_logic;                      -- 全部零片已锁定
        o_solved      : out std_logic                       -- 并集 == 目标图案
    );
end entity puzzle_ctrl;

architecture rtl of puzzle_ctrl is

    -- ============================================================
    -- 类型与常量
    -- ============================================================
    -- 每块零片的锚点：{行[2:0], 列[2:0]}，打包成 6 位（省触发器，CLAUDE.md §10.2 ③）
    type anchor_t is array (0 to 3) of std_logic_vector(5 downto 0);

    -- 回退锚点表（两关共用一张）：左上 / 右上 / 左下 / 右下
    --   零片最大 3×3 → 行方向 0~2 与 5~7 不交、列方向同理 → 四个锚点两两不重叠，
    --   且都满足锚点不变量（行 6 不行：高 3 的块会占到不存在的第 8 行）。
    type fb_t is array (0 to 3) of integer range 0 to 7;
    constant FB_ROW : fb_t := (0, 0, 5, 5);
    constant FB_COL : fb_t := (0, 5, 0, 5);

    -- ============================================================
    -- 内部状态
    -- ============================================================
    signal r_anchor : anchor_t;                     -- 4×6 = 24 个触发器
    signal r_locked : std_logic_vector(3 downto 0); --  4 个
    signal r_sel    : std_logic_vector(1 downto 0); --  2 个

    -- 散落序列器（9 个 + 2 个）
    type seq_state_t is (ST_IDLE, ST_STEP, ST_TRY, ST_DEC);
    signal r_seq     : seq_state_t;                 -- 2 个（4 个状态）
    signal r_piece   : integer range 0 to 3;        -- 2 个
    signal r_try     : integer range 0 to 7;        -- 3 个
    signal r_fb      : integer range 0 to 3;        -- 2 个
    signal r_fb_mode : std_logic;                   -- 1 个：0 = 随机尝试，1 = 走回退表
    signal r_free    : std_logic;                   -- 1 个：包围盒判据的**寄存结果**

    -- 行扫描引擎（时分复用，4 块 × 8 行 = 32 拍一帧）
    signal r_eng_p    : integer range 0 to 3;       -- 当前处理第几块
    signal r_eng_row  : integer range 0 to 7;       -- 当前处理第几个输出行（7 → 0）
    signal r_eng_run  : std_logic;                  -- 1 = 一帧正在刷新
    signal r_eng_chk  : std_logic;                  -- 1 = 最后一拍（定型判定的那一拍）
    signal r_acc_red  : std_logic_vector(7 downto 0);  -- 当前行的红色累加器
    signal r_acc_grn  : std_logic_vector(7 downto 0);  -- 当前行的绿色累加器
    signal r_px_red   : std_logic_vector(63 downto 0);
    signal r_px_green : std_logic_vector(63 downto 0);
    signal r_mismatch : std_logic;                  -- 并集 ≠ 目标（复位为 1 = "未拼对"）

    -- 引擎的组合输入/输出
    signal s_eng_ac   : integer range 0 to 7;           -- 当前块的列锚点
    signal s_eng_j    : integer range -7 to 7;          -- 当前输出行对应块内第几行
    signal s_eng_h    : integer range 0 to 7;           -- 当前块的高
    signal s_eng_rp   : std_logic_vector(2 downto 0);   -- 相对掩码第 j 行（3 位）
    signal s_eng_rowv : std_logic_vector(7 downto 0);   -- 列移位后的行内容
    signal s_eng_red  : std_logic;                      -- 本块画成红色
    signal s_eng_grn  : std_logic;                      -- 本块画成绿色
    signal s_eng_vld  : std_logic;                      -- 本块存在（p < 块数）
    signal s_eng_contrib : std_logic_vector(7 downto 0);-- 本拍的合法行贡献
    signal s_red_contrib : std_logic_vector(7 downto 0);-- 归入红色的贡献
    signal s_grn_contrib : std_logic_vector(7 downto 0);-- 归入绿色的贡献
    signal s_fin_red  : std_logic_vector(7 downto 0);   -- 本行的最终红色
    signal s_fin_grn  : std_logic_vector(7 downto 0);   -- 本行的最终绿色
    signal s_eng_go   : std_logic;                      -- 刷新请求脉冲

    -- 其它组合量
    signal s_valid_mask  : std_logic_vector(3 downto 0);  -- 本关哪几块存在
    signal s_sel_idx     : integer range 0 to 3;          -- r_sel 的整数形式
    signal s_new_anchor  : std_logic_vector(5 downto 0);  -- 移动的候选新锚点

    -- 散落序列器的握手信号
    signal s_cand_row    : integer range 0 to 7;
    signal s_cand_col    : integer range 0 to 7;
    signal s_cand_h      : integer range 0 to 7;          -- 候选块的高 / 宽
    signal s_cand_w      : integer range 0 to 7;
    signal s_free_c      : std_logic;                     -- 包围盒判据（组合结果）
    signal s_sc_we       : std_logic;                     -- 本拍要写锚点
    signal s_sc_idx      : integer range 0 to 3;
    signal s_sc_anchor   : std_logic_vector(5 downto 0);

    -- ============================================================
    -- 图案参数的**寄存副本**（r_h / r_w / r_count）
    --   ※ 不是为了"存数据"，是为了**切断时序关键路径**：
    --      i_height / i_width / i_piece_count 来自 piece_rom（纯组合），
    --      而 piece_rom 的输入是 game_fsm 的 o_pattern_sel。
    --      不寄存时，一条组合链是
    --        r_state → o_pattern_sel → piece_rom → 包围盒判据 → 散落序列器 → r_try
    --      实测 22.3ns，Fmax 只有 44MHz。寄存一级后这条链被切成两段。
    --   ※ 寄存带来的 1 拍延迟不影响功能：散落序列器要在 o_round_start
    --      之后至少 2 拍才用到这些数据，而 o_pattern_sel 本身也已寄存。
    -- ============================================================
    signal r_h     : dim_arr_t;             -- 12 个触发器
    signal r_w     : dim_arr_t;             -- 12 个触发器
    signal r_count : integer range 0 to 7;  --  3 个触发器

begin

    -- 图案参数采样（每拍跟踪输入）
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_h     <= (others => (others => '0'));
                r_w     <= (others => (others => '0'));
                r_count <= 0;
            else
                r_h     <= i_height;
                r_w     <= i_width;
                r_count <= to_integer(unsigned(i_piece_count));
            end if;
        end if;
    end process;

    -- ============================================================
    -- ① 本关哪几块存在（由 r_count 展开）
    --    ★ 比较器写法在任何 count 下都对（不要写成移位，count=0 时会算错）
    -- ============================================================
    s_valid_mask(0) <= '1';
    s_valid_mask(1) <= '1' when r_count > 1 else '0';
    s_valid_mask(2) <= '1' when r_count > 2 else '0';
    s_valid_mask(3) <= '1' when r_count > 3 else '0';

    s_sel_idx <= to_integer(unsigned(r_sel));   -- slv 不能作数组下标

    -- ============================================================
    -- ② 行扫描引擎的输入选择（组合）
    --    ※ 零片的相对掩码只在前 3 行 × 前 3 列有非零位（docs/02 §8.3），
    --       故"取第 j 行"只需 3 个 3 位切片之间的选择。
    -- ============================================================
    s_eng_ac <= to_integer(unsigned(r_anchor(r_eng_p)(2 downto 0)));
    s_eng_h  <= to_integer(unsigned(r_h(r_eng_p)));
    s_eng_j  <= r_eng_row - to_integer(unsigned(r_anchor(r_eng_p)(5 downto 3)));

    -- 本块是否存在（不存在 → 贡献恒 0）
    s_eng_vld <= '1' when r_eng_p < r_count else '0';

    -- 配色：锁定 → 红+绿（黄）；选中 → 绿；其余 → 红
    s_eng_red <= '1' when (r_locked(r_eng_p) = '1') or
                          (unsigned(r_sel) /= to_unsigned(r_eng_p, 2)) else '0';
    s_eng_grn <= '1' when (r_locked(r_eng_p) = '1') or
                          (unsigned(r_sel) = to_unsigned(r_eng_p, 2)) else '0';

    -- 取相对掩码的第 j 行（3 位）；j 不在 0~2 时给 0
    process (s_eng_j, r_eng_p, i_rel_mask)
    begin
        case s_eng_j is
            when 0      => s_eng_rp <= i_rel_mask(r_eng_p)(2 downto 0);
            when 1      => s_eng_rp <= i_rel_mask(r_eng_p)(10 downto 8);
            when 2      => s_eng_rp <= i_rel_mask(r_eng_p)(18 downto 16);
            when others => s_eng_rp <= "000";
        end case;
    end process;

    -- 列移位：把 3 位行模式按列锚点 ac 平移到 8 位列上
    --   ★ 写成与常量比较（ac = c-k），不要写 (ac+k) = c —— 前者能折叠成译码，
    --     后者会让综合器去搭加法器。位号越界（c-k 不为 0~7）在编译期就被消掉。
    process (s_eng_rp, s_eng_ac)
        variable v : std_logic_vector(7 downto 0);
    begin
        v := (others => '0');
        for c in 0 to 7 loop
            for k in 0 to 2 loop
                if (c - k) >= 0 and (c - k) <= 7 then
                    if s_eng_rp(k) = '1' and s_eng_ac = (c - k) then
                        v(c) := '1';
                    end if;
                end if;
            end loop;
        end loop;
        s_eng_rowv <= v;
    end process;

    -- 行贡献：行号必须在块内（0 ≤ j < 高）且本块存在，否则整行丢弃
    s_eng_contrib <= s_eng_rowv
                     when (s_eng_vld = '1' and s_eng_j >= 0 and s_eng_j < s_eng_h)
                     else (others => '0');

    -- 按配色把贡献分流到红 / 绿两路（锁定 → 两路都进 = 黄；选中 → 只进绿；其余 → 只进红）
    s_red_contrib <= s_eng_contrib when s_eng_red = '1' else (others => '0');
    s_grn_contrib <= s_eng_contrib when s_eng_grn = '1' else (others => '0');

    -- 本行的最终红 / 绿内容（含本拍贡献）
    s_fin_red <= r_acc_red or s_red_contrib;
    s_fin_grn <= r_acc_grn or s_grn_contrib;

    -- 刷新请求：任何会改变画面的输入出现时，重新跑一帧
    s_eng_go <= '1' when (i_round_start = '1' or s_sc_we = '1' or
                          i_sel = '1' or i_conf = '1' or i_dir /= "0000")
                else '0';

    -- ============================================================
    -- ③ 行扫描引擎（时序）：32 拍刷新一帧
    --    行序是 **7 → 0（从下往上）**，这是"移位写回"能成立的前提：
    --    写回用 `reg <= reg(55 downto 0) & 本行` —— 左移 8 位、新行补在最低 8 位，
    --    于是**最后处理的行留在最上面**。倒着走完 8 行后，
    --    行 R 正好落在 bit 8R..8R+7（与位序约定 bit0 = 左上角 一致）。
    --    这样写回是"纯接线 + 一个时钟使能"，不需要 64 位的静态保持多路器。
    --    · 每行 4 拍累加（块 0→3）；第 3 块那一拍顺便做判定：
    --      把本行并集与目标行比较，任何一行不等就置 r_mismatch
    --      → 省掉一个独立的 64 位比较器。
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_px_red   <= (others => '0');
                r_px_green <= (others => '0');
                r_acc_red  <= (others => '0');
                r_acc_grn  <= (others => '0');
                r_eng_p    <= 0;
                r_eng_row  <= 7;
                r_eng_run  <= '0';
                r_eng_chk  <= '0';
                r_mismatch <= '1';              -- 复位后 = "还没拼对"
            else
                if s_eng_go = '1' then
                    -- 新一帧：从第 0 块、最下面一行（行 7）开始
                    r_eng_p    <= 0;
                    r_eng_row  <= 7;
                    r_eng_run  <= '1';
                    r_eng_chk  <= '0';
                    r_mismatch <= '0';
                elsif r_eng_run = '1' then
                    if r_eng_chk = '1' then
                        -- ★ 判定拍：画面寄存器此时已经定型（最后一次移位已完成），
                        --   所以这里是"寄存器 → 比较器"的短路径；
                        --   若把比较塞在行累加那一拍里（用组合的 s_fin_* 去比），
                        --   关键路径会变成 25.7ns → Fmax 只有 38MHz（实测）。
                        if (r_px_red or r_px_green) /= i_target_mask then
                            r_mismatch <= '1';
                        end if;
                        r_eng_chk <= '0';
                        r_eng_run <= '0';
                    else
                        -- 行累加器：本行第 0 块时重新开始，其余块或入
                        if r_eng_p = 0 then
                            r_acc_red <= s_red_contrib;
                            r_acc_grn <= s_grn_contrib;
                        else
                            r_acc_red <= r_acc_red or s_red_contrib;
                            r_acc_grn <= r_acc_grn or s_grn_contrib;
                        end if;

                        if r_eng_p = 3 then
                            -- 本行定型：整行移入画面寄存器
                            -- （左移 8 位 + 新行补在最低 8 位）
                            r_px_red   <= r_px_red(55 downto 0)   & s_fin_red;
                            r_px_green <= r_px_green(55 downto 0) & s_fin_grn;
                        end if;

                        -- 推进：行从 7 递减到 0，然后换下一块
                        if r_eng_row = 0 then
                            r_eng_row <= 7;
                            if r_eng_p = 3 then
                                r_eng_chk <= '1';   -- 最后一行已定型 → 下一拍判定
                            else
                                r_eng_p <= r_eng_p + 1;
                            end if;
                        else
                            r_eng_row <= r_eng_row - 1;
                        end if;
                    end if;
                end if;
            end if;
        end if;
    end process;

    o_px_red   <= r_px_red;
    o_px_green <= r_px_green;

    -- ============================================================
    -- ④ 判定输出
    --    ※ "全 1 检测"必须加括号：VHDL 的关系运算符比逻辑运算符**紧**，
    --       r_locked and s_valid_mask = s_valid_mask 会被解析成
    --       r_locked and (s_valid_mask = s_valid_mask) → 类型错误（ERR-0012）。
    --    ※ o_solved 必须在**刷新期间保持为 '0'**：刷新一开始 r_mismatch 被清零，
    --       若此时直接输出 not r_mismatch，就会在"最后一块刚锁定"的那 32 拍里
    --       假报"拼对了"→ 状态机立刻误判胜利。用 r_eng_run 把它门控掉。
    --    两个输出都是组合的；且只在 S_PLAYING 有意义（进 S_WIN/S_FAIL 后
    --    i_target_mask 变成胜负显示图案，会凑出"全锁但没拼对"的假象，
    --    所以判失败那条边必须写在 game_fsm 的 S_PLAYING 分支里）。
    -- ============================================================
    o_all_locked <= '1' when (r_locked and s_valid_mask) = s_valid_mask else '0';
    o_solved     <= '1' when (r_eng_run = '0') and (r_mismatch = '0') else '0';

    -- ============================================================
    -- ⑤ 散落：候选锚点（组合）
    --    r_fb_mode = 0：用随机数，钳位到 [0, 8-高] / [0, 8-宽]（与移动钳位同一把尺子）
    --    r_fb_mode = 1：用回退表第 r_fb 项
    --    ★ 候选在 ST_TRY / ST_DEC 两拍内保持不变（i_rnd 只在 ST_STEP 那一拍更新），
    --      所以"判据结果寄存一拍"不会错位。
    -- ============================================================
    process (r_fb_mode, r_piece, r_fb, i_rnd, r_h, r_w)
        variable v_row  : integer range 0 to 7;
        variable v_col  : integer range 0 to 7;
        variable v_maxr : integer range 0 to 8;   -- 行锚点上限 = 8 - 高
        variable v_maxc : integer range 0 to 8;   -- 列锚点上限 = 8 - 宽
    begin
        v_row := to_integer(unsigned(i_rnd(5 downto 3)));
        v_col := to_integer(unsigned(i_rnd(2 downto 0)));

        v_maxr := 8 - to_integer(unsigned(r_h(r_piece)));
        v_maxc := 8 - to_integer(unsigned(r_w (r_piece)));

        -- 钳位：让每次尝试都落在合法范围。v_maxr 可能取到 8（占位槽高 = 0），
        -- 此时 v_row ≤ 7 < 8，分支不会执行。
        if v_row > v_maxr then v_row := v_maxr; end if;
        if v_col > v_maxc then v_col := v_maxc; end if;

        if r_fb_mode = '1' then                   -- 回退：直接用表里的锚点
            v_row := FB_ROW(r_fb);
            v_col := FB_COL(r_fb);
        end if;

        s_cand_row <= v_row;
        s_cand_col <= v_col;
    end process;

    -- 候选块（当前正在摆的那一块）的高 / 宽
    s_cand_h <= to_integer(unsigned(r_h(r_piece)));
    s_cand_w <= to_integer(unsigned(r_w (r_piece)));

    -- 重叠判定（保守 · 包围盒不相交）
    --   候选块 (行,列,高,宽) 与已放置的第 q 块，包围盒相交 当且仅当 四个不等式同时成立。
    --   ※ 只比较"已放置"的前 r_piece 块；不能把还没摆的块算进去
    --      （那是 s_union 的语义，用它求交恒非空 → 每次都判重叠 → 全部走回退）。
    process (s_cand_row, s_cand_col, s_cand_h, s_cand_w,
             r_piece, r_anchor, r_h, r_w)
        variable v_hit  : std_logic;
        variable v_r2   : integer range 0 to 7;
        variable v_c2   : integer range 0 to 7;
        variable v_h2   : integer range 0 to 7;
        variable v_w2   : integer range 0 to 7;
    begin
        v_hit := '0';
        for q in 0 to 3 loop
            if q < r_piece then
                v_r2 := to_integer(unsigned(r_anchor(q)(5 downto 3)));
                v_c2 := to_integer(unsigned(r_anchor(q)(2 downto 0)));
                v_h2 := to_integer(unsigned(r_h(q)));
                v_w2 := to_integer(unsigned(r_w (q)));
                if (s_cand_row < v_r2 + v_h2) and (v_r2 < s_cand_row + s_cand_h) and
                   (s_cand_col < v_c2 + v_w2) and (v_c2 < s_cand_col + s_cand_w) then
                    v_hit := '1';
                end if;
            end if;
        end loop;
        s_free_c <= not v_hit;
    end process;

    -- ★ 判据结果寄存一拍（仅 1 个触发器），把"包围盒比较"与"序列器决策"
    --   切成两段：不寄存时数据延迟 20.4ns、裕量 -0.4ns（Fmax 差一点点）。
    --   代价：每次尝试从 2 拍变 3 拍 → 48 次尝试 × 3 拍 ≈ 2.9μs，远小于 5 秒预览。
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_free <= '0';
            else
                r_free <= s_free_c;
            end if;
        end if;
    end process;

    -- ============================================================
    -- ⑥ 散落序列器（有界尝试 + 确定性回退，保证有限步内一定终止）
    --    每次尝试占 **三拍**：
    --      ST_STEP 发 o_rnd_step（单周期脉冲，LFSR 在这一拍前进）
    --      ST_TRY  候选锚点稳定，包围盒判据算出并被 r_free 寄存
    --      ST_DEC  按 r_free 决策：写入锚点 / 再试一次 / 转回退
    --    ※ 不能压成两拍：① rng_lfsr 在 i_step 的那个时钟沿才更新，"同一拍读 i_rnd"
    --       读到的是旧值（§9.5 那个"每次同值"的坑会重现）；② 判据必须寄存，
    --       否则 piece_rom → 包围盒比较 → 序列器 会连成一条 20.4ns 的组合链。
    --    上界：4 块 ×（8 次随机 + 4 次回退）× 3 拍 = 144 拍 ≈ 2.9μs @50MHz，
    --          由 i_round_start 在 S_PREVIEW 入口触发，远早于预览结束（5 秒）。
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_seq      <= ST_IDLE;
                r_piece    <= 0;
                r_try      <= 0;
                r_fb       <= 0;
                r_fb_mode  <= '0';
                o_rnd_step <= '0';
                s_sc_we    <= '0';
            else
                o_rnd_step <= '0';              -- 默认：脉冲宽度 = 1 个 clk
                s_sc_we    <= '0';

                case r_seq is
                    when ST_IDLE =>
                        r_piece   <= 0;
                        r_try     <= 0;
                        r_fb      <= 0;
                        r_fb_mode <= '0';
                        if i_round_start = '1' then
                            r_seq <= ST_STEP;   -- 新一局 → 开始散落
                        end if;

                    when ST_STEP =>
                        o_rnd_step <= '1';      -- ★ 每次尝试都推进一步 LFSR
                        r_seq      <= ST_TRY;

                    when ST_TRY =>
                        r_seq <= ST_DEC;        -- 等 r_free 把本候选的判据寄存好

                    when others =>              -- ST_DEC：决策拍
                        if r_free = '1' then
                            -- 找到可放的位置 → 记下锚点，换下一块
                            s_sc_we     <= '1';
                            s_sc_idx    <= r_piece;
                            s_sc_anchor <= std_logic_vector(to_unsigned(s_cand_row, 3)) &
                                           std_logic_vector(to_unsigned(s_cand_col, 3));
                            if r_piece = r_count - 1 then
                                r_seq <= ST_IDLE;           -- 全部摆完
                            else
                                r_piece   <= r_piece + 1;
                                r_try     <= 0;
                                r_fb      <= 0;
                                r_fb_mode <= '0';
                                r_seq     <= ST_STEP;
                            end if;
                        elsif r_fb_mode = '0' then
                            if r_try < 7 then
                                r_try <= r_try + 1;         -- 再随机试一次
                                r_seq <= ST_STEP;
                            else
                                r_fb      <= 0;             -- 8 次都不行 → 转回退
                                r_fb_mode <= '1';
                                r_seq     <= ST_TRY;        -- 让 r_free 重算这一项
                            end if;
                        elsif r_fb < 3 then
                            r_fb <= r_fb + 1;               -- 顺序检查表内下一项
                            r_seq <= ST_TRY;
                        else
                            -- 理论不可达（四个角对高/宽 ≤ 3 的块必有一个可用）。
                            -- 保底：仍然写入，保证序列器**有限终止、绝不死锁**。
                            s_sc_we     <= '1';
                            s_sc_idx    <= r_piece;
                            s_sc_anchor <= std_logic_vector(to_unsigned(s_cand_row, 3)) &
                                           std_logic_vector(to_unsigned(s_cand_col, 3));
                            if r_piece = r_count - 1 then
                                r_seq <= ST_IDLE;
                            else
                                r_piece   <= r_piece + 1;
                                r_try     <= 0;
                                r_fb      <= 0;
                                r_fb_mode <= '0';
                                r_seq     <= ST_STEP;
                            end if;
                        end if;
                end case;
            end if;
        end if;
    end process;

    -- ============================================================
    -- ⑦ 锚点写入 —— ★ r_anchor 的**唯一写者**
    --    三档优先级（物理上必须是同一个进程，否则就是多重驱动）：
    --      1 复位 > 2 散落序列器 > 3 方向键移动
    --    三者在时间上互斥（散落只在 S_PREVIEW 期、移动只在 S_PLAYING 期）。
    --    ※ 移动的前提是"该块未锁定"（要求 8）。
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_anchor <= (others => (others => '0'));
            elsif s_sc_we = '1' then
                r_anchor(s_sc_idx) <= s_sc_anchor;
            elsif i_dir /= "0000" and r_locked(s_sel_idx) = '0' then
                r_anchor(s_sel_idx) <= s_new_anchor;
            end if;
        end if;
    end process;

    -- ============================================================
    -- ⑧ 移动与钳位（要求 7 的核心）—— 组合：由当前锚点算出候选新锚点
    --    ★ 策略是"**先判断，再决定改不改**"，不是"先加减、再把越界值修补回来"：
    --       v_row / v_col 全程被 range 0 to 7 约束，越界的中间值根本不会被算出来。
    --    ★ 下标一律用 s_sel_idx（整数）：r_sel 是 slv，不能作数组下标。
    -- ============================================================
    process (s_sel_idx, r_anchor, i_dir, r_h, r_w, r_count)
        variable v_row  : integer range 0 to 7;
        variable v_col  : integer range 0 to 7;
        variable v_h    : integer range 0 to 7;
        variable v_w    : integer range 0 to 7;
        variable v_maxr : integer range 0 to 8;    -- 行锚点上限 = 8 - 高
        variable v_maxc : integer range 0 to 8;    -- 列锚点上限 = 8 - 宽
    begin
        v_row := to_integer(unsigned(r_anchor(s_sel_idx)(5 downto 3)));
        v_col := to_integer(unsigned(r_anchor(s_sel_idx)(2 downto 0)));
        v_h   := to_integer(unsigned(r_h(s_sel_idx)));
        v_w   := to_integer(unsigned(r_w (s_sel_idx)));
        v_maxr := 8 - v_h;      -- 不变量：行锚点 + 高 ≤ 8
        v_maxc := 8 - v_w;

        case i_dir is
            when "1000" =>                                  -- 上
                if v_row > 0 then
                    v_row := v_row - 1;
                end if;
            when "0100" =>                                  -- 下
                -- ★ 守卫"本块必须真的存在"：占位槽的高 = 0 → v_maxr 会算出 8，
                --   若让它自增，"先判断再改"就不够用了（7 + 1 = 8 会越界）
                if (s_sel_idx < r_count) and (v_row < v_maxr) then
                    v_row := v_row + 1;
                end if;
            when "0010" =>                                  -- 左
                if v_col > 0 then
                    v_col := v_col - 1;
                end if;
            when "0001" =>                                  -- 右
                if v_col < v_maxc then
                    v_col := v_col + 1;
                end if;
            when others =>
                null;                                       -- 无方向脉冲 → 不动
        end case;

        s_new_anchor <= std_logic_vector(to_unsigned(v_row, 3)) &
                        std_logic_vector(to_unsigned(v_col, 3));
    end process;

    -- ============================================================
    -- ⑨ "选择"键（要求 6）：循环切换，且跳过已锁定的块
    --    ★ 用变量 v_next 迭代（变量赋值立即生效）；循环界是常量，最多转 4 圈必定停下。
    --    ※ 判据用 >= 而不是 =：写 = 时，一个陈旧的 v_next = 3 在 v_last = 2 时
    --       （第二关打完回到第一关）会跳进 else 分支算出 4 → 越界。
    --    ※ 不用 mod：piece_count 是信号，mod 会综合出一个除法器。
    -- ============================================================
    process (clk)
        variable v_next : integer range 0 to 3;
        variable v_last : integer range 0 to 3;    -- 本关最后一块的序号
    begin
        if rising_edge(clk) then
            if rst = '1' or i_round_start = '1' then
                r_sel <= "00";                     -- ★ 新一局也归零：块数可能变少
            elsif i_sel = '1' then
                v_next := to_integer(unsigned(r_sel));
                v_last := r_count - 1;
                for k in 0 to 3 loop               -- ★ 循环界是常量
                    if v_next >= v_last then
                        v_next := 0;               -- 绕回第 0 块
                    else
                        v_next := v_next + 1;
                    end if;
                    exit when r_locked(v_next) = '0';   -- 找到未锁定的就停
                end loop;
                r_sel <= std_logic_vector(to_unsigned(v_next, 2));
            end if;
        end if;
    end process;

    -- ============================================================
    -- ⑩ "确认"键（要求 8）：锁定当前零片
    --    语义：锁定，**不立即判定**；等全部锁定后由 game_fsm 用 o_solved 判定
    --    （零片初始位置随机，每锁一块就查"位置对不对"必然立刻判失败）。
    -- ============================================================
    process (clk)
    begin
        if rising_edge(clk) then
            if rst = '1' then
                r_locked <= (others => '0');
            elsif i_round_start = '1' then
                r_locked <= (others => '0');            -- 新一局：清锁定
            elsif i_conf = '1' and r_locked(s_sel_idx) = '0' then
                r_locked(s_sel_idx) <= '1';             -- 锁定（不可再选、不可再动）
            end if;
        end if;
    end process;

end architecture rtl;

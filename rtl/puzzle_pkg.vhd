-- ============================================================
--  puzzle_pkg —— 全局常量与掩码运算包
--  所属子系统：—（包，不属于任何子系统；不产生任何硬件）
--  职责：全局常量、掩码纯函数、位序约定（全项目唯一真值源）
--  对应需求：全部（各模块共用）
--
--  ※ 本包只有 constant 与 function，没有信号、没有进程。
--     所有函数都是纯组合（无信号赋值、无 wait），可被综合器展开。
--  ※ 常量的值单点定义在 docs/02-模块详细设计.md §2.5 / §2.6 / §2.7，
--     任何模块、任何其它文档都只引用、不重列。
--  位序约定（docs/01 §4.3）：mask(8*行 + 列)，bit0 = 左上角；
--     行内 bit0 = 最左列；「向右移一列」= 行向量左移。
-- ============================================================

library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

package puzzle_pkg is

    -- ============================================================
    -- 数组类型（供端口使用：零片是 4 块，形状要成组传）
    --   VHDL-93 的端口不能用匿名数组，类型必须在包里声明一次，
    --   这样 component 声明与实体声明才同型（docs/01 §5.0）。
    -- ============================================================
    type mask_arr_t is array (0 to 3) of std_logic_vector(63 downto 0);  -- 4 块零片掩码
    type dim_arr_t  is array (0 to 3) of std_logic_vector(2 downto 0);   -- 4 块的高/宽

    -- 全 0 掩码常量：比较"某个与/或结果是否为空"时比 (others => '0') 更好用
    constant MASK_ZERO : std_logic_vector(63 downto 0) := (others => '0');

    -- ============================================================
    -- 掩码纯函数（只保留这 2 个；全项目没有主路径调用点，
    --   用途是离线核对与自检，见 docs/02 §2.4 / §2.8）
    -- ============================================================
    function shift_right_col(m : std_logic_vector(63 downto 0))
        return std_logic_vector;            -- 逐行右移一列（教学样例）
    function popcount(m : std_logic_vector(63 downto 0)) return integer;
                                            -- 数 1 的个数（验证点与离线核对用）

    -- ============================================================
    -- 图案常量（实测数据，勿手工改动）
    --   数据来源：python scripts/verify_tiling.py
    --   修改任何图案前必须先跑该脚本，确认格数守恒且合法铺法仍存在。
    -- ============================================================

    -- 第一关：4 行 × 3 列实心矩形（点阵第 2~5 行、第 2~4 列），共 12 格
    constant L1_TARGET_MASK : std_logic_vector(63 downto 0) :=
        "0000000000000000000111000001110000011100000111000000000000000000";

    -- 第二关（主用）：向上箭头，共 18 格
    constant L2_TARGET_MASK : std_logic_vector(63 downto 0) :=
        "0000000000011000000110000001100001111110001111000001100000000000";

    -- 第二关（备用）：向下箭头，共 18 格
    constant L2B_TARGET_MASK : std_logic_vector(63 downto 0) :=
        "0000000000011000001111000111111000011000000110000001100000000000";

    -- 零片相对掩码（锚点 = 包围盒左上角，已对齐到 bit0）
    --   第一关 3 块（6+3+3 = 12 格）
    --     零片0: 6 格 3×3     零片1: 3 格 2×2     零片2: 3 格 1×3
    constant L1_P0 : std_logic_vector(63 downto 0) :=
        "0000000000000000000000000000000000000000000000010000001100000111";
    constant L1_P1 : std_logic_vector(63 downto 0) :=
        "0000000000000000000000000000000000000000000000000000001100000010";
    constant L1_P2 : std_logic_vector(63 downto 0) :=
        "0000000000000000000000000000000000000000000000000000000000000111";

    --   第二关（上箭头）4 块（6+6+4+2 = 18 格）
    constant L2_P0 : std_logic_vector(63 downto 0) :=
        "0000000000000000000000000000000000000000000001110000011000000100";
    constant L2_P1 : std_logic_vector(63 downto 0) :=
        "0000000000000000000000000000000000000000000001110000001100000001";
    constant L2_P2 : std_logic_vector(63 downto 0) :=
        "0000000000000000000000000000000000000000000000000000001100000011";
    constant L2_P3 : std_logic_vector(63 downto 0) :=
        "0000000000000000000000000000000000000000000000000000000000000011";

    --   第二关（下箭头）4 块：L2 各块的上下翻转（已穷举验证可铺）
    --   零片0 与第一关零片0 同形；只有零片1 是新形状
    constant L2B_P0 : std_logic_vector(63 downto 0) := L1_P0;
    constant L2B_P1 : std_logic_vector(63 downto 0) :=
        "0000000000000000000000000000000000000000000001000000011000000111";
    constant L2B_P2 : std_logic_vector(63 downto 0) := L2_P2;
    constant L2B_P3 : std_logic_vector(63 downto 0) := L2_P3;

    -- 胜利图案：对勾，15 格（位图见 docs/02 §7.4）
    constant WIN_MASK : std_logic_vector(63 downto 0) :=
        "0000000000000100000011100001101100110001011000001100000000000000";

    -- 失败图案：叉，24 格
    constant FAIL_MASK : std_logic_vector(63 downto 0) :=
        "0000000011000011011001100011110000111100011001101100001100000000";

    -- 零片包围盒的最大边长（3）：所有零片的高/宽都 ≤ 3，
    -- 且相对掩码只在前 3 行 × 前 3 列上有非零位（docs/02 §8.3 的数据表）。
    -- puzzle_ctrl 的 place() 依赖这一条来省面积（遍历范围 3×3 而不是 8×8）。
    constant PIECE_MAX_DIM : integer := 3;

    -- ============================================================
    -- 分频与时间常量（★ 唯一定义处，见 docs/02 §2.6）
    -- ============================================================
    -- ★ 串行级联：只有第 1 级面对 50MHz，其余各级只数"上一级来了几个脉冲"
    constant CLK_HZ    : integer := 50_000_000;         -- ★ 板上时钟档位必须为 7
    constant CNT_8K    : integer := CLK_HZ / 8_000 - 1; -- 50MHz→8kHz，分频比 6250
    constant CNT_1K    : integer := 8_000 / 1_000 - 1;  -- 8kHz→1kHz，  分频比 8
    constant CNT_100   : integer := 1_000 / 100   - 1;  -- 1kHz→100Hz， 分频比 10
    constant CNT_2HZ   : integer := 100   / 2     - 1;  -- 100Hz→2Hz，  分频比 50
    constant CNT_1HZ   : integer := 100   / 1     - 1;  -- 100Hz→1Hz，  分频比 100

    -- 上电复位时长：★ 实现上数的是 tick_1k（1ms/拍），不再直数 clk。
    --   原方案 CNT_POR = CLK_HZ/100-1 = 499999 → 19 位计数器；改数 tick_1k 只要 4 位。
    --   （EPM1270 只有 1270 个 LE，实测这一步是必要的；tick_1k 由本模块的分频链
    --     自由运行产生、不依赖复位，所以上电即可用。总时长仍是 10ms 量级。）
    constant T_POR_MS  : integer := 10;   -- 上电复位时长（ms）

    constant T_PREVIEW : integer := 5;    -- 预览秒数（要求 4）
    constant T_LEVEL1  : integer := 30;   -- 第一关限时（要求 5）
    constant T_LEVEL2  : integer := 40;   -- 第二关限时（要求 10）
    constant T_SELFTEST: integer := 2;    -- 开机自检秒数（要求 1）

    -- 消抖：数的是"扫描轮次"，一轮 = 4 个 i_tick = 4ms（1kHz）→ 20 轮 = 80ms
    constant DEBOUNCE_MAX : integer := 19;    -- 计到 19 即 20 轮（计数器从 0 起算）

    -- 按键复位消抖：数的是 tick_1k（1ms/拍）→ 20 拍 = 20ms
    constant T_BTN_MS    : integer := 20;     -- 复位键消抖时长（ms）
    constant DEBOUNCE_BTN: integer := T_BTN_MS - 1;   -- 计到 19 即 20 拍

    -- 方向键连发：两个数都数 i_tick_100，即每 100ms 减 1
    constant REPEAT_DELAY  : integer := 5;    -- 按住 5 × 100ms = 500ms 后开始连发
    constant REPEAT_PERIOD : integer := 1;    -- 之后每 1 × 100ms = 100ms 重复一次

    -- 随机源：LFSR 复位初值，★ 8 位全非零，绝不能是全 0（吸收态）
    constant SEED_DEFAULT : std_logic_vector(7 downto 0) := x"01";

    -- 自检闪烁：tick_100 数 25 个得 4Hz，再翻转得 2Hz 方波
    constant CNT_BLINK  : integer := 24;      -- 计 0~24 共 25 拍

    -- ============================================================
    -- 状态编码常量（game_fsm 按它赋值、disp_format 按它分支）
    --   3 位编码（6 个状态，不用 one-hot）
    --   用 subtype 而不是自定义枚举类型，是为了让 i_state 端口保持
    --   std_logic_vector(2 downto 0) —— 端口类型一变，接口表与顶层
    --   component 声明都要跟着改。
    -- ============================================================
    subtype state_t is std_logic_vector(2 downto 0);

    constant S_SELF_TEST : state_t := "000";   -- 开机自检（2 秒，2Hz 闪烁）
    constant S_IDLE      : state_t := "001";   -- 待机
    constant S_PREVIEW   : state_t := "010";   -- 图案预览（5 秒倒计时）
    constant S_PLAYING   : state_t := "011";   -- 拼图中（限时倒计时）
    constant S_WIN       : state_t := "100";   -- 胜利
    constant S_FAIL      : state_t := "101";   -- 失败

end package puzzle_pkg;


-- ============================================================
--  包体：实现上面声明的两个纯函数
-- ============================================================
library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

package body puzzle_pkg is

    -- 逐行右移一列：★ 绝不能写成 m sll 1 之类的整体移位
    --   整体移位会让第 r 行最右列（bit 8r+7）跑到第 r+1 行最左列（bit 8r+8）
    --   —— 像素"穿墙"到下一行开头，正是要求 7 要防的边界错误。
    function shift_right_col(m : std_logic_vector(63 downto 0))
        return std_logic_vector is
        variable v : std_logic_vector(63 downto 0);
    begin
        for r in 0 to 7 loop
            -- 取第 r 行低 7 位，后面补 '0'（补在最右，即列号最大处）
            v(8*r+7 downto 8*r) := m(8*r+6 downto 8*r) & '0';
        end loop;
        return v;
    end function;

    -- 数 1 的个数（用于调试与自检，不参与主逻辑）
    function popcount(m : std_logic_vector(63 downto 0)) return integer is
        variable n : integer range 0 to 64 := 0;   -- ★ 必须带 range，否则综合成 32 位
    begin
        for i in 0 to 63 loop
            if m(i) = '1' then
                n := n + 1;
            end if;
        end loop;
        return n;
    end function;

end package body puzzle_pkg;

# 跨题共用常量(随机种子/场景参数/权重等)。各题脚本请:
#   from config import SEED, ...
# 禁止在 problemN.py 里另设不同取值。

from pathlib import Path

# ---------- 随机性 ----------
SEED = 42

# ---------- 数值计算 ----------
EPS = 1e-9              # 一般数值判零阈值
TOL = 1e-6              # 迭代收敛阈值
MAX_ITER = 10000        # 迭代求解最大步数

# ---------- Monte Carlo / 抽样 ----------
N_MC = 2000             # 蒙特卡洛默认样本数
N_BOOTSTRAP = 1000      # Bootstrap 重抽样次数
CI_ALPHA = 0.05         # 置信区间显著性水平(95% CI)

# ---------- 灵敏度分析 ----------
SENS_DELTA = 0.10       # 参数扰动幅度(±10%)
SENS_GRID = 11          # 扫描点数

# ---------- 优化求解 ----------
OPT_TOL = 1e-8          # 优化收敛阈值
OPT_MAX_ITER = 5000     # 优化最大迭代次数

# ---------- 输出路径(按本文件位置定位工程根,与当前工作目录无关) ----------
# ROOT 为工程根(src/ 的上一级)。各脚本请统一从此处取路径,
# 不要写 "../figures" 之类的相对路径。
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"        # 原始/处理后数据目录
FIG_DIR = ROOT / "figures"      # 图像输出目录(主图 figures/problemN.png)
RES_DIR = ROOT / "results"      # 数值结果/表格输出目录
# 兼容旧命名
OUT_DIR = RES_DIR

# ---------- 数据文件 ----------
FILE_A1 = DATA_DIR / "附件1.xlsx"   # 单日:时间/电价/小区负载/光伏发电预测功率
FILE_A2 = DATA_DIR / "附件2.xlsx"   # 多日:小区负载 / 光伏发电实际功率
FILE_A3 = DATA_DIR / "附件3.xlsx"
FILE_A4 = DATA_DIR / "附件4.xlsx"

# ---------- 时间粒度 ----------
DT_MIN = 10                     # 采样/调度时间步长(分钟)
DT_HOUR = DT_MIN / 60.0         # 时间步长(小时),用于能量=功率*时间
STEPS_PER_DAY = 24 * 60 // DT_MIN  # 每日时段数(=144)

# ---------- 储能系统(BESS)参数 ----------
BATT_ETA_CH = 0.95              # 充电效率
BATT_ETA_DIS = 0.95             # 放电效率
BATT_SOC_MIN = 0.10             # 最小荷电状态
BATT_SOC_MAX = 0.90             # 最大荷电状态
BATT_SOC_INIT = 0.50            # 初始荷电状态
BATT_C_RATE = 0.5               # 最大充放电倍率(相对额定容量,1/h)
BATT_DOD = BATT_SOC_MAX - BATT_SOC_MIN   # 可用放电深度
BATT_LIFE_CYCLES = 6000         # 循环寿命(次)
BATT_COST_PER_KWH = 1500.0      # 储能单位容量投资成本(元/kWh)
BATT_COST_PER_KW = 800.0        # 储能单位功率投资成本(元/kW)

# ---------- 并网/购售电 ----------
GRID_P_MAX = 1e6                # 并网点最大交换功率(kW),按需收紧
SELL_PRICE_RATIO = 1.0          # 上网电价相对购电电价的比例(如不允许套利可设<1)

# ---------- 绘图通用 ----------
FIG_SIZE = (6.0, 4.0)   # 默认图幅(英寸)
LINE_WIDTH = 1.6        # 默认线宽
MARKER_SIZE = 5         # 默认 marker 大小

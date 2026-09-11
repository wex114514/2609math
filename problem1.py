"""
问题1: 确定型典型日下的日前计划购电与储能充放电优化
--------------------------------------------------------------
建立以10分钟为时段的线性规划(LP):
- 决策变量: 每时段外网购电量g_t、储能充电量c_t、放电量d_t、储能电量SOC_t
- 目标: min Σ_t π_t·g_t (购电总费用,元)
- 约束:
  1) 供电充足性: g_t + P_pv,t·Δt + d_t - c_t >= L_t·Δt
  2) SOC递推: SOC_t = SOC_{t-1} + η·c_t - d_t/η
  3) SOC边界: SOC_min <= SOC_t <= SOC_max
  4) 充放电功率限: 0 <= c_t, d_t <= P_max·Δt
  5) 首末电量相等: SOC_0 = SOC_144 = 6000 kWh
  6) 购电非负: g_t >= 0

使用 scipy.optimize.linprog (method='highs') 求解全局最优。
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib
matplotlib.use("Agg")

import numpy as np
import pandas as pd
from pathlib import Path
from scipy.optimize import linprog
import matplotlib.pyplot as plt
import json

from config import (
    SEED, FILE_A1, FIG_DIR, RES_DIR,
    DT_HOUR, STEPS_PER_DAY,
    BATT_ETA_CH, BATT_ETA_DIS, BATT_SOC_MIN, BATT_SOC_MAX, BATT_SOC_INIT,
    BATT_C_RATE, BATT_COST_PER_KWH
)
from plot_style import apply, PALETTE, figsize, series_style

apply()
np.random.seed(SEED)

# 确保输出目录存在
FIG_DIR.mkdir(parents=True, exist_ok=True)
RES_DIR.mkdir(parents=True, exist_ok=True)

# ========== 参数设定 ==========
E_CAP = 12000.0         # 储能容量 (kWh)
P_MAX = 5000.0          # 最大充放电功率 (kW)
ETA = 0.9               # 充放电效率
SOC_MIN = 1200.0        # 最小SOC (kWh)
SOC_MAX = 10800.0       # 最大SOC (kWh)
SOC_INIT = 6000.0       # 初始/末态SOC (kWh)
DT = DT_HOUR            # 时间步长 (小时) = 1/6
T = STEPS_PER_DAY       # 时段数 = 144

# 单时段充放电电量上限 (kWh)
C_MAX = P_MAX * DT      # ≈ 833.33 kWh
D_MAX = P_MAX * DT

print("=" * 60)
print("问题1: 确定型典型日优化")
print("=" * 60)
print(f"储能容量: {E_CAP} kWh")
print(f"最大充放电功率: {P_MAX} kW")
print(f"充放电效率: {ETA}")
print(f"SOC运行区间: [{SOC_MIN}, {SOC_MAX}] kWh")
print(f"初始/末态SOC: {SOC_INIT} kWh")
print(f"时段数: {T}, 时间步长: {DT} h")
print(f"单时段充放电上限: {C_MAX:.2f} kWh")
print()

# ========== 读取附件1数据 ==========
print("读取附件1数据...")
df = pd.read_excel(FILE_A1, sheet_name='Sheet1')
print(f"数据形状: {df.shape}")
print(f"列名: {df.columns.tolist()}")
print(df.head())

# 提取数据(功率单位 kW, 电价单位 元/kWh)
price = df['电价'].values          # π_t (元/kWh)
load = df['小区负载'].values       # L_t (kW)
pv = df['光伏发电预测功率'].values  # P_pv,t (kW)

assert len(price) == T, f"电价数据点数{len(price)}与时段数{T}不符"
assert len(load) == T, f"负载数据点数{len(load)}与时段数{T}不符"
assert len(pv) == T, f"光伏数据点数{len(pv)}与时段数{T}不符"

print(f"电价范围: [{price.min():.4f}, {price.max():.4f}] 元/kWh")
print(f"负载范围: [{load.min():.2f}, {load.max():.2f}] kW")
print(f"光伏范围: [{pv.min():.2f}, {pv.max():.2f}] kW")
print()

# ========== 构建线性规划 ==========
"""
决策变量顺序(共 4*T = 576维):
  x = [g_0, g_1, ..., g_{T-1},      # 购电量 (kWh)
       c_0, c_1, ..., c_{T-1},      # 充电量 (kWh)
       d_0, d_1, ..., d_{T-1},      # 放电量 (kWh)
       SOC_0, SOC_1, ..., SOC_{T-1}] # 储能电量 (kWh)

目标函数: min Σ_t π_t * g_t
约束:
  1) 供电充足性(T个): g_t + P_pv,t*DT + d_t - c_t >= L_t*DT
  2) SOC递推(T个): SOC_t = SOC_{t-1} + ETA*c_t - d_t/ETA  (t=0时 SOC_{-1}=SOC_INIT)
  3) SOC下界(T个): SOC_t >= SOC_MIN
  4) SOC上界(T个): SOC_t <= SOC_MAX
  5) 充电上限(T个): c_t <= C_MAX
  6) 放电上限(T个): d_t <= D_MAX
  7) 首末电量相等(1个): SOC_{T-1} = SOC_INIT
  8) 变量非负: g_t, c_t, d_t >= 0 (通过bounds设定)
"""

print("构建线性规划...")

n_vars = 4 * T
idx_g = np.arange(0, T)
idx_c = np.arange(T, 2*T)
idx_d = np.arange(2*T, 3*T)
idx_soc = np.arange(3*T, 4*T)

# 目标函数系数: c = [π_0, π_1, ..., π_{T-1}, 0, ..., 0]
c = np.zeros(n_vars)
c[idx_g] = price

# 变量边界: g, c, d >= 0, SOC无直接bounds(通过约束控制)
bounds = [(0, None)] * (3*T) + [(None, None)] * T

# 不等式约束 A_ub @ x <= b_ub
# 我们转换为标准形式(所有约束改写为 <=)
A_ub = []
b_ub = []

# 1) 供电充足性: g_t + P_pv,t*DT + d_t - c_t >= L_t*DT
#    => -(g_t + d_t - c_t) <= -L_t*DT + P_pv,t*DT
for t in range(T):
    row = np.zeros(n_vars)
    row[idx_g[t]] = -1.0    # -g_t
    row[idx_c[t]] = 1.0     # +c_t
    row[idx_d[t]] = -1.0    # -d_t
    A_ub.append(row)
    b_ub.append(-load[t] * DT + pv[t] * DT)

# 2) SOC递推写成不等式(等式拆成两个不等式):
#    SOC_t = SOC_{t-1} + ETA*c_t - d_t/ETA
#    => SOC_t - ETA*c_t + d_t/ETA - SOC_{t-1} = 0
#    拆成: SOC_t - ETA*c_t + d_t/ETA - SOC_{t-1} <= 0
#          -SOC_t + ETA*c_t - d_t/ETA + SOC_{t-1} <= 0
# 但用等式约束更简洁,我们用 A_eq

# 3) SOC下界: SOC_t >= SOC_MIN => -SOC_t <= -SOC_MIN
for t in range(T):
    row = np.zeros(n_vars)
    row[idx_soc[t]] = -1.0
    A_ub.append(row)
    b_ub.append(-SOC_MIN)

# 4) SOC上界: SOC_t <= SOC_MAX
for t in range(T):
    row = np.zeros(n_vars)
    row[idx_soc[t]] = 1.0
    A_ub.append(row)
    b_ub.append(SOC_MAX)

# 5) 充电上限: c_t <= C_MAX
for t in range(T):
    row = np.zeros(n_vars)
    row[idx_c[t]] = 1.0
    A_ub.append(row)
    b_ub.append(C_MAX)

# 6) 放电上限: d_t <= D_MAX
for t in range(T):
    row = np.zeros(n_vars)
    row[idx_d[t]] = 1.0
    A_ub.append(row)
    b_ub.append(D_MAX)

A_ub = np.array(A_ub)
b_ub = np.array(b_ub)

# 等式约束 A_eq @ x = b_eq
A_eq = []
b_eq = []

# SOC递推(T个): SOC_t - ETA*c_t + (d_t/ETA) - SOC_{t-1} = 0
for t in range(T):
    row = np.zeros(n_vars)
    row[idx_soc[t]] = 1.0           # SOC_t
    row[idx_c[t]] = -ETA            # -ETA*c_t
    row[idx_d[t]] = 1.0 / ETA       # d_t/ETA
    if t == 0:
        # SOC_0 - ETA*c_0 + d_0/ETA = SOC_INIT
        b_eq.append(SOC_INIT)
    else:
        row[idx_soc[t-1]] = -1.0    # -SOC_{t-1}
        b_eq.append(0.0)
    A_eq.append(row)

# 首末电量相等(1个): SOC_{T-1} = SOC_INIT
row = np.zeros(n_vars)
row[idx_soc[T-1]] = 1.0
A_eq.append(row)
b_eq.append(SOC_INIT)

A_eq = np.array(A_eq)
b_eq = np.array(b_eq)

print(f"决策变量维度: {n_vars}")
print(f"不等式约束数: {A_ub.shape[0]}")
print(f"等式约束数: {A_eq.shape[0]}")
print()

# ========== 求解 ==========
print("开始求解LP(使用HiGHS)...")
result = linprog(
    c=c,
    A_ub=A_ub, b_ub=b_ub,
    A_eq=A_eq, b_eq=b_eq,
    bounds=bounds,
    method='highs',
    options={'disp': True, 'presolve': True}
)

if not result.success:
    print("求解失败!")
    print(result.message)
    exit(1)

print("求解成功!")
print(f"最优目标值(全天购电费): {result.fun:.2f} 元")
print()

# 提取解
x_opt = result.x
g_opt = x_opt[idx_g]     # 购电量 (kWh)
c_opt = x_opt[idx_c]     # 充电量 (kWh)
d_opt = x_opt[idx_d]     # 放电量 (kWh)
soc_opt = x_opt[idx_soc] # 储能电量 (kWh)

# ========== 验证约束满足 ==========
print("验证约束满足...")

# 供电充足性
supply = g_opt + pv * DT + d_opt - c_opt
demand = load * DT
deficit = demand - supply
max_deficit = deficit.max()
print(f"供电缺口最大值: {max_deficit:.6f} kWh (应<=0)")

# SOC递推
soc_check = np.zeros(T)
soc_check[0] = SOC_INIT + ETA * c_opt[0] - d_opt[0] / ETA
for t in range(1, T):
    soc_check[t] = soc_check[t-1] + ETA * c_opt[t] - d_opt[t] / ETA
soc_error = np.abs(soc_opt - soc_check).max()
print(f"SOC递推最大误差: {soc_error:.6e} kWh")

# SOC边界
soc_min_viol = (SOC_MIN - soc_opt).max()
soc_max_viol = (soc_opt - SOC_MAX).max()
print(f"SOC下界违反: {soc_min_viol:.6f} kWh (应<=0)")
print(f"SOC上界违反: {soc_max_viol:.6f} kWh (应<=0)")

# 首末电量相等
soc_final_error = abs(soc_opt[-1] - SOC_INIT)
print(f"首末电量偏差: {soc_final_error:.6e} kWh")

# 充放电上限
c_max_viol = (c_opt - C_MAX).max()
d_max_viol = (d_opt - D_MAX).max()
print(f"充电上限违反: {c_max_viol:.6f} kWh (应<=0)")
print(f"放电上限违反: {d_max_viol:.6f} kWh (应<=0)")
print()

# ========== 统计结果 ==========
total_purchase_kwh = g_opt.sum()    # 全天购电量 (kWh)
total_cost = result.fun              # 全天购电费 (元)
total_charge = c_opt.sum()           # 全天充电量 (kWh)
total_discharge = d_opt.sum()        # 全天放电量 (kWh)

print("=" * 60)
print("求解结果统计")
print("=" * 60)
print(f"全天购电量: {total_purchase_kwh:.2f} kWh")
print(f"全天购电费: {total_cost:.2f} 元")
print(f"全天充电量: {total_charge:.2f} kWh")
print(f"全天放电量: {total_discharge:.2f} kWh")
print(f"储能初始电量: {SOC_INIT:.2f} kWh")
print(f"储能末态电量: {soc_opt[-1]:.2f} kWh")
print()

# ========== 表1: 指定时段购电量 ==========
# 题目要求6个10分钟段: 10:00-10:10, 12:00-12:10, 14:00-14:10, 16:00-16:10, 18:00-18:10, 20:00-20:10
# 对应时段索引(从0:00开始,每10分钟一个点):
# 10:00 -> 60个10分钟 = 索引60
# 12:00 -> 72
# 14:00 -> 84
# 16:00 -> 96
# 18:00 -> 108
# 20:00 -> 120
specified_times = ['10:00-10:10', '12:00-12:10', '14:00-14:10', 
                   '16:00-16:10', '18:00-18:10', '20:00-20:10']
specified_idx = [60, 72, 84, 96, 108, 120]

print("表1: 指定时段购电量")
print("-" * 60)
print(f"{'时间段':<15} {'购电量(kWh)':<15}")
print("-" * 60)
for time_str, idx in zip(specified_times, specified_idx):
    print(f"{time_str:<15} {g_opt[idx]:<15.4f}")
print(f"{'全天购电量':<15} {total_purchase_kwh:<15.2f}")
print(f"{'全天购电费(元)':<15} {total_cost:<15.2f}")
print()

# ========== 表2: 4小时段充放电汇总 ==========
# 6个4小时段: 0-4, 4-8, 8-12, 12-16, 16-20, 20-24
# 每个4小时段包含 4*6 = 24个10分钟时段
periods = ['0-4时', '4-8时', '8-12时', '12-16时', '16-20时', '20-24时']
period_starts = [0, 24, 48, 72, 96, 120]  # 时段索引
period_charge = []
period_discharge = []

for i, start in enumerate(period_starts):
    end = start + 24
    charge_sum = c_opt[start:end].sum()
    discharge_sum = d_opt[start:end].sum()
    period_charge.append(charge_sum)
    period_discharge.append(discharge_sum)

print("表2: 4小时段充放电汇总")
print("-" * 60)
print(f"{'时段':<10} {'充电量(kWh)':<20} {'放电量(kWh)':<20}")
print("-" * 60)
for period, ch, dis in zip(periods, period_charge, period_discharge):
    print(f"{period:<10} {ch:<20.2f} {dis:<20.2f}")
print(f"{'0:00储电量':<10} {SOC_INIT:<20.2f}")
print(f"{'24:00储电量':<10} {soc_opt[-1]:<20.2f}")
print()

# ========== 导出result1.xlsx ==========
print("导出result1.xlsx...")
from openpyxl import Workbook

wb = Workbook()

# 工作表1: 计划购电量(144个10分钟时段)
ws1 = wb.active
ws1.title = "计划购电量"
ws1.append(["时段索引", "时间", "购电量(kWh)"])
for t in range(T):
    hour = t * 10 // 60
    minute = (t * 10) % 60
    time_str = f"{hour:02d}:{minute:02d}"
    ws1.append([t, time_str, g_opt[t]])

# 工作表2: 充放电量(分段汇总)
ws2 = wb.create_sheet("充放电量")
ws2.append(["时段", "充电量(kWh)", "放电量(kWh)"])
for period, ch, dis in zip(periods, period_charge, period_discharge):
    ws2.append([period, ch, dis])
ws2.append(["0:00储电量", SOC_INIT, ""])
ws2.append(["24:00储电量", soc_opt[-1], ""])

result_file = RES_DIR / "result1.xlsx"
wb.save(result_file)
print(f"已保存: {result_file}")
print()

# ========== 导出results/problem1.json ==========
results_dict = {
    "problem": "问题1: 确定型典型日优化",
    "method": "线性规划(LP, HiGHS)",
    "parameters": {
        "E_cap_kWh": E_CAP,
        "P_max_kW": P_MAX,
        "eta": ETA,
        "SOC_min_kWh": SOC_MIN,
        "SOC_max_kWh": SOC_MAX,
        "SOC_init_kWh": SOC_INIT,
        "time_steps": T,
        "dt_hour": DT
    },
    "optimal_solution": {
        "total_cost_yuan": round(total_cost, 2),
        "total_purchase_kWh": round(total_purchase_kwh, 2),
        "total_charge_kWh": round(total_charge, 2),
        "total_discharge_kWh": round(total_discharge, 2),
        "SOC_final_kWh": round(soc_opt[-1], 2)
    },
    "table1_specified_periods": {
        time_str: round(g_opt[idx], 4) 
        for time_str, idx in zip(specified_times, specified_idx)
    },
    "table2_period_summary": {
        period: {"charge_kWh": round(ch, 2), "discharge_kWh": round(dis, 2)}
        for period, ch, dis in zip(periods, period_charge, period_discharge)
    },
    "constraint_check": {
        "max_supply_deficit_kWh": round(max_deficit, 6),
        "SOC_recursion_error_kWh": round(soc_error, 6),
        "SOC_min_violation_kWh": round(soc_min_viol, 6),
        "SOC_max_violation_kWh": round(soc_max_viol, 6),
        "SOC_final_error_kWh": round(soc_final_error, 6),
        "charge_limit_violation_kWh": round(c_max_viol, 6),
        "discharge_limit_violation_kWh": round(d_max_viol, 6)
    }
}

json_file = RES_DIR / "problem1.json"
with open(json_file, 'w', encoding='utf-8') as f:
    json.dump(results_dict, f, ensure_ascii=False, indent=2)
print(f"已保存: {json_file}")
print()

# ========== 绘图 ==========
print("生成图表...")

# 时间轴(小时)
time_hours = np.arange(T) * DT

# 图1: 主图 - 购电、光伏、负载、SOC时序
fig, axes = plt.subplots(2, 1, figsize=figsize('default', rows=2),
                         sharex=True, constrained_layout=True)

# 上图: 功率/电量
ax1 = axes[0]
ax1.plot(time_hours, g_opt / DT, label='购电功率', color=PALETTE[0], linewidth=1.5)
ax1.plot(time_hours, pv, label='光伏发电', color=PALETTE[1], linewidth=1.5, linestyle='--')
ax1.plot(time_hours, load, label='小区负载', color=PALETTE[2], linewidth=1.5, linestyle='-.')
ax1.fill_between(time_hours, 0, c_opt / DT, label='充电功率', color=PALETTE[3], alpha=0.3)
ax1.fill_between(time_hours, 0, d_opt / DT, label='放电功率', color=PALETTE[4], alpha=0.3)
ax1.set_ylabel('功率 (kW)')
ax1.legend(loc='upper left', fontsize=9)
ax1.grid(True, alpha=0.3)

# 下图: SOC
ax2 = axes[1]
ax2.plot(time_hours, soc_opt, label='储能电量 SOC', color=PALETTE[5], linewidth=2)
ax2.axhline(SOC_MIN, color=PALETTE[1], linestyle='--',
            linewidth=1.2, label='SOC下限')
ax2.axhline(SOC_MAX, color=PALETTE[2], linestyle=':',
            linewidth=1.2, label='SOC上限')
ax2.axhline(SOC_INIT, color='gray', linestyle='-.', linewidth=1, label='初始/目标值')
ax2.set_xlabel('时间 (小时)')
ax2.set_ylabel('电量 (kWh)')
ax2.legend(loc='upper left', fontsize=9)
ax2.grid(True, alpha=0.3)

fig_main = FIG_DIR / "problem1.png"
plt.savefig(fig_main, dpi=300)
print(f"已保存: {fig_main}")
plt.close()

# 图2: 数据预览 - 电价、负载、光伏
fig, axes = plt.subplots(3, 1, figsize=figsize('default', rows=3),
                         sharex=True, constrained_layout=True)

ax1 = axes[0]
ax1.plot(time_hours, price, color=PALETTE[0], linewidth=1.5)
ax1.set_ylabel('电价 (元/kWh)')
ax1.grid(True, alpha=0.3)
ax1.set_title('附件1数据预览')

ax2 = axes[1]
ax2.plot(time_hours, load, color=PALETTE[2], linewidth=1.5)
ax2.set_ylabel('小区负载 (kW)')
ax2.grid(True, alpha=0.3)

ax3 = axes[2]
ax3.plot(time_hours, pv, color=PALETTE[1], linewidth=1.5)
ax3.set_ylabel('光伏发电 (kW)')
ax3.set_xlabel('时间 (小时)')
ax3.grid(True, alpha=0.3)

fig_data = FIG_DIR / "problem1_data.png"
plt.savefig(fig_data, dpi=300)
print(f"已保存: {fig_data}")
plt.close()

# 图3: 诊断图 - SOC轨迹与能量守恒
fig, axes = plt.subplots(2, 1, figsize=figsize('default', rows=2),
                         sharex=True, constrained_layout=True)

# 上图: SOC与电价叠加(展示套利结构)
ax1 = axes[0]
ax1_twin = ax1.twinx()
ax1.plot(time_hours, soc_opt, color=PALETTE[5], linewidth=2, label='SOC')
ax1.axhline(SOC_MIN, color=PALETTE[1], linestyle='--', linewidth=1.0, alpha=0.6)
ax1.axhline(SOC_MAX, color=PALETTE[2], linestyle=':', linewidth=1.0, alpha=0.6)
ax1.set_ylabel('SOC (kWh)', color=PALETTE[5])
ax1.tick_params(axis='y', labelcolor=PALETTE[5])
ax1.grid(True, alpha=0.3)

ax1_twin.plot(time_hours, price, color=PALETTE[0], linewidth=1.5, linestyle=':', label='电价')
ax1_twin.set_ylabel('电价 (元/kWh)', color=PALETTE[0])
ax1_twin.tick_params(axis='y', labelcolor=PALETTE[0])

ax1.set_title('SOC轨迹与电价(低价充电、高价放电)')

# 下图: 能量守恒残差
supply_check = g_opt + pv * DT + d_opt - c_opt
demand_check = load * DT
balance = supply_check - demand_check
ax2 = axes[1]
ax2.plot(time_hours, balance, color=PALETTE[3], linewidth=1.5)
ax2.axhline(0, color='black', linestyle='--', linewidth=1)
ax2.set_ylabel('供需平衡 (kWh)')
ax2.set_xlabel('时间 (小时)')
ax2.set_title('能量守恒检查(应>=0)')
ax2.grid(True, alpha=0.3)

fig_diag = FIG_DIR / "problem1_diagnostic.png"
plt.savefig(fig_diag, dpi=300)
print(f"已保存: {fig_diag}")
plt.close()

print()
print("=" * 60)
print("问题1求解完成!")
print("=" * 60)
print("产物清单:")
print(f"  - 结果文件: {result_file}")
print(f"  - JSON结果: {json_file}")
print(f"  - 主图: {fig_main}")
print(f"  - 数据图: {fig_data}")
print(f"  - 诊断图: {fig_diag}")
print()
print("核心结论:")
print(f"  1. 全天购电费: {total_cost:.2f} 元")
print(f"  2. 全天购电量: {total_purchase_kwh:.2f} kWh")
print(f"  3. 储能充放电平衡: 充{total_charge:.2f} kWh, 放{total_discharge:.2f} kWh")
print(f"  4. SOC始终在[{SOC_MIN}, {SOC_MAX}]内, 首末电量均为{SOC_INIT} kWh")
print(f"  5. 所有约束满足, 最大违反量: {max(max_deficit, soc_min_viol, soc_max_viol, c_max_viol, d_max_viol):.6e}")
print()

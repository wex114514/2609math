"""问题3: 波动电价+滚动MPC(夏至日6.21示例)"""
import matplotlib
matplotlib.use("Agg")
from pathlib import Path
import sys
import numpy as np

# 允许从工程根目录或任意工作目录启动脚本时导入根目录模块。
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import pandas as pd
import json
import matplotlib.pyplot as plt
from plot_style import apply, PALETTE, series_style
from config import SEED, DT_HOUR, STEPS_PER_DAY
from microgrid import (
    solve_window, load_daily_matrix, load_price_volatile,
    load_pv_forecast, interp_forecast_to_10min,
    SOC_INIT, DT, T
)
import datetime as dtm

apply()
np.random.seed(SEED)

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "figures"
RES = ROOT / "results"
FIG.mkdir(exist_ok=True)
RES.mkdir(exist_ok=True)

print("="*60)
print("问题3: 波动电价 + 滚动MPC(夏至日6.21)")
print("="*60)

# ========== 数据加载 ==========
dates_load, load_mat = load_daily_matrix('小区负载')
dates_pv, pv_mat = load_daily_matrix('光伏发电实际功率')
dates_price, price_mat = load_price_volatile()
fc_dict = load_pv_forecast()

# 夏至日: 2025-06-21
target_date = dtm.date(2025, 6, 21)
day_idx = np.where(dates_load == target_date)[0][0]
print(f"目标日期: {target_date} (索引{day_idx})")

load_real = load_mat[day_idx, :]  # 真实负载
pv_real = pv_mat[day_idx, :]      # 真实光伏
price_day = price_mat[day_idx, :] # 波动电价

# ========== MPC设置 ==========
# 每6小时(36个时段)执行一次优化,共4次: 0/6/12/18点
issue_hours = [0, 6, 12, 18]
horizon = 24  # 预测时域(小时)

# 存储MPC执行的计划与真实执行
g_plan_mpc = np.zeros(T)  # 各时段计划购电
c_exec = np.zeros(T)      # 实际充电
d_exec = np.zeros(T)      # 实际放电
soc_exec = np.zeros(T+1)  # SOC轨迹(0..144)
soc_exec[0] = SOC_INIT

print(f"\nMPC参数: 预测时域={horizon}h, 发布时刻={issue_hours}")

for i, issue_h in enumerate(issue_hours):
    print(f"\n--- 第{i+1}次MPC: {issue_h}:00 ---")
    
    # 当前时段索引: issue_h*6
    t_start = issue_h * 6
    
    # 获取预报
    key = (target_date, issue_h)
    if key not in fc_dict:
        print(f"  警告: 无{issue_h}:00预报,跳过")
        continue
    fc24 = fc_dict[key]
    
    # 插值预报到10分钟粒度(覆盖当天剩余时段)
    pv_fc_rest = interp_forecast_to_10min(issue_h, fc24)
    n_rest = len(pv_fc_rest)  # (24 - issue_h)*6
    
    # 构造优化窗口: 从t_start到24:00
    load_window = load_real[t_start : t_start + n_rest]
    price_window = price_day[t_start : t_start + n_rest]
    pv_window = pv_fc_rest
    
    # 当前SOC
    soc_now = soc_exec[t_start]
    
    # 求解LP:
    #  - 中间窗口(0/6/12点): 不设末端SOC约束,让储能自由跨窗口决策,
    #    避免"每6小时被迫回归到6000"导致的额外购电.
    #  - 最后一次窗口(18点): 末端SOC回到SOC_INIT,保证日际循环闭合.
    soc_final = SOC_INIT if i == len(issue_hours) - 1 else None
    sol = solve_window(price_window, load_window, pv_window,
                       soc_now, soc_final)
    
    if not sol['success']:
        print(f"  LP失败: {sol.get('message','')}")
        continue
    
    # 只执行到下一个发布时刻(或24:00)
    if i < len(issue_hours) - 1:
        next_h = issue_hours[i+1]
        n_exec = (next_h - issue_h) * 6
    else:
        n_exec = n_rest
    
    # 提取执行段
    g_exec_seg = sol['g'][:n_exec]
    c_exec_seg = sol['c'][:n_exec]
    d_exec_seg = sol['d'][:n_exec]
    soc_seg = sol['soc'][:n_exec]
    
    # 回滚到真实光伏下的SOC演化
    for k in range(n_exec):
        t = t_start + k
        # 按计划购电/充放电,真实光伏
        g_plan_mpc[t] = g_exec_seg[k]
        c_exec[t] = c_exec_seg[k]
        d_exec[t] = d_exec_seg[k]
        
        # SOC递推(真实): soc[t+1] = soc[t] + eta*c - d/eta
        from microgrid import ETA
        soc_exec[t+1] = soc_exec[t] + ETA * c_exec[t] - d_exec[t] / ETA
    
    print(f"  执行 {n_exec} 时段, SOC {soc_exec[t_start]:.1f} -> {soc_exec[t_start+n_exec]:.1f} kWh")

# ========== 结算 ==========
# 结算时,计划购电只计入g_plan_mpc,实时补购只计入实际供电缺口。
# 光伏与充放电均按10分钟能量折算,避免把功率值直接当成电量。
demand = load_real * DT
pv_energy_real = pv_real * DT
planned_supply = g_plan_mpc + pv_energy_real + d_exec - c_exec
e_mpc = np.maximum(0.0, demand - planned_supply)

plan_cost = float(np.dot(price_day, g_plan_mpc))
emergency_cost = float(np.dot(5.0 * price_day, e_mpc))
total_cost = plan_cost + emergency_cost

print(f"\n{'='*60}")
print("MPC结算结果")
print(f"{'='*60}")
print(f"计划购电成本: {plan_cost:,.2f} 元")
print(f"紧急购电成本: {emergency_cost:,.2f} 元")
print(f"总成本:       {total_cost:,.2f} 元")
print(f"计划购电量:   {g_plan_mpc.sum():,.2f} kWh")
print(f"紧急购电量:   {e_mpc.sum():,.2f} kWh")
print(f"充电量:       {c_exec.sum():,.2f} kWh")
print(f"放电量:       {d_exec.sum():,.2f} kWh")
print(f"初始SOC:      {soc_exec[0]:.2f} kWh")
print(f"末态SOC:      {soc_exec[-1]:.2f} kWh")

# ========== 导出Excel ==========
times = [f"{h:02d}:{m:02d}:00" for h in range(24) for m in [10,20,30,40,50,60]][:T]
df_out = pd.DataFrame({
    '时间': times,
    '电价(元/kWh)': price_day,
    '真实负载(kW)': load_real,
    '真实光伏(kW)': pv_real,
    '计划购电(kWh)': g_plan_mpc,
    '紧急购电(kWh)': e_mpc,
    '充电(kWh)': c_exec,
    '放电(kWh)': d_exec,
    'SOC(kWh)': soc_exec[1:]  # 末态
})

excel_path = RES / "result3.xlsx"
with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
    summary = pd.DataFrame({
        '指标': ['计划购电成本(元)', '紧急购电成本(元)', '总成本(元)',
                '计划购电量(kWh)', '紧急购电量(kWh)',
                '充电量(kWh)', '放电量(kWh)'],
        '数值': [plan_cost, emergency_cost, total_cost,
                g_plan_mpc.sum(), e_mpc.sum(),
                c_exec.sum(), d_exec.sum()]
    })
    summary.to_excel(writer, sheet_name='汇总', index=False)
    df_out.to_excel(writer, sheet_name='逐时段明细', index=False)

print(f"\n已保存: {excel_path}")

# ========== 导出JSON ==========
json_path = RES / "problem3.json"
with open(json_path, 'w', encoding='utf-8') as f:
    json.dump({
        'date': str(target_date),
        'summary': {
            'plan_cost': float(plan_cost),
            'emergency_cost': float(emergency_cost),
            'total_cost': float(total_cost)
        },
        'timeseries': {
            'price': price_day.tolist(),
            'load': load_real.tolist(),
            'pv': pv_real.tolist(),
            'g_plan': g_plan_mpc.tolist(),
            'emergency': e_mpc.tolist(),
            'charge': c_exec.tolist(),
            'discharge': d_exec.tolist(),
            'soc': soc_exec.tolist()
        }
    }, f, indent=2, ensure_ascii=False)
print(f"已保存: {json_path}")

# ========== 绘图: 2x2 组图,避免竖排3面板挤压 ==========
print("\n生成图表...")
from plot_style import figsize
from microgrid import SOC_MIN, SOC_MAX
fig, axes = plt.subplots(2, 2, figsize=figsize('wide', rows=2),
                         constrained_layout=True)
x = np.arange(T)

ax = axes[0, 0]
ax.plot(x, price_day, label='波动电价', **series_style('波动电价'))
ax.set_ylabel('电价 (元/kWh)')
ax.set_title('(a) 波动电价')
ax.grid(True, alpha=0.3)

ax = axes[0, 1]
ax.plot(x, load_real, label='负载', **series_style('负载'))
ax.plot(x, pv_real, label='光伏', **series_style('光伏'))
ax.set_ylabel('功率 (kW)')
ax.set_title('(b) 负载与光伏')
ax.legend(loc='best')
ax.grid(True, alpha=0.3)

ax = axes[1, 0]
net_storage = c_exec - d_exec
ax.plot(x, g_plan_mpc, label='计划购电', **series_style('计划购电'))
ax.plot(x, net_storage, label='净充放电', **series_style('净充放电'))
ax.axhline(0.0, color='black', linestyle=':', linewidth=0.8)
ax.set_ylabel('能量 (kWh/10min)')
ax.set_xlabel('时段(10分钟)')
ax.set_title('(c) 购电与净充放电')
ax.legend(loc='best')
ax.grid(True, alpha=0.3)

ax = axes[1, 1]
ax.plot(x, soc_exec[1:], label='SOC', **series_style('SOC'))
ax.axhline(SOC_MIN, color=PALETTE[1], linestyle='--',
           linewidth=1.2, label='SOC下限')
ax.axhline(SOC_MAX, color=PALETTE[2], linestyle=':',
           linewidth=1.2, label='SOC上限')
ax.set_ylabel('SOC (kWh)')
ax.set_xlabel('时段(10分钟)')
ax.set_title('(d) SOC轨迹')
ax.legend(loc='best')
ax.grid(True, alpha=0.3)

fig_path = FIG / "problem3.png"
plt.savefig(fig_path, dpi=300)
plt.close()
print(f"已保存: {fig_path}")

print(f"\n{'='*60}")
print("问题3求解完成!")
print(f"{'='*60}")
print(f"产物清单:")
print(f"  - 结果文件: {excel_path}")
print(f"  - JSON结果: {json_path}")
print(f"  - 主图: {fig_path}")
print(f"\n核心结论:")
print(f"  1. MPC总成本: {total_cost:,.2f} 元(夏至日)")
print(f"  2. 紧急购电: {e_mpc.sum():.2f} kWh(成本{emergency_cost:,.2f}元)")
print(f"  3. SOC始末: {soc_exec[0]:.1f} -> {soc_exec[-1]:.1f} kWh")

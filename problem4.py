"""问题4: 波动电价+全年MPC(2025.2.1 - 12.31共334天)"""
import matplotlib
matplotlib.use("Agg")
from pathlib import Path
import numpy as np
import pandas as pd
import json
import matplotlib.pyplot as plt
from plot_style import apply, PALETTE
from config import SEED, DT_HOUR, STEPS_PER_DAY
from microgrid import (
    solve_window, load_daily_matrix, load_price_volatile,
    load_pv_forecast, interp_forecast_to_10min,
    SOC_INIT, DT, T, ETA
)

apply()
np.random.seed(SEED)

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "figures"
RES = ROOT / "results"
FIG.mkdir(exist_ok=True)
RES.mkdir(exist_ok=True)

print("="*60)
print("问题4: 波动电价 + 全年MPC(2.1~12.31)")
print("="*60)

# ========== 数据加载 ==========
dates_load, load_mat = load_daily_matrix('小区负载')
dates_pv, pv_mat = load_daily_matrix('光伏发电实际功率')
dates_price, price_mat = load_price_volatile()
fc_dict = load_pv_forecast()

start_idx = 31
end_idx = 364
n_days = end_idx - start_idx + 1
print(f"模拟日期: {dates_load[start_idx]} ~ {dates_load[end_idx]}, 共 {n_days} 天")

# ========== MPC设置 ==========
issue_hours = [0, 6, 12, 18]
horizon = 24

# ========== 逐日MPC ==========
daily_results = []

for day_idx in range(start_idx, end_idx + 1):
    date = dates_load[day_idx]
    load_real = load_mat[day_idx, :]
    pv_real = pv_mat[day_idx, :]
    price_day = price_mat[day_idx, :]
    
    # 初始化当日执行轨迹
    g_plan_mpc = np.zeros(T)
    c_exec = np.zeros(T)
    d_exec = np.zeros(T)
    soc_exec = np.zeros(T+1)
    soc_exec[0] = SOC_INIT
    
    # 逐时段MPC
    for i, issue_h in enumerate(issue_hours):
        t_start = issue_h * 6
        
        key = (date, issue_h)
        if key not in fc_dict:
            # 无预报则跳过该次优化,维持不充放电
            if i < len(issue_hours) - 1:
                next_h = issue_hours[i+1]
                n_exec = (next_h - issue_h) * 6
            else:
                n_exec = T - t_start
            # 不充放电,直接购电满足需求
            for k in range(n_exec):
                t = t_start + k
                demand_kWh = load_real[t] * DT
                pv_kWh = pv_real[t] * DT
                g_plan_mpc[t] = max(0.0, demand_kWh - pv_kWh)
                soc_exec[t+1] = soc_exec[t]
            continue
        
        fc24 = fc_dict[key]
        pv_fc_rest = interp_forecast_to_10min(issue_h, fc24)
        n_rest = len(pv_fc_rest)
        
        load_window = load_real[t_start : t_start + n_rest]
        price_window = price_day[t_start : t_start + n_rest]
        pv_window = pv_fc_rest
        soc_now = soc_exec[t_start]
        
        sol = solve_window(price_window, load_window, pv_window,
                           soc_now, SOC_INIT)
        
        if not sol['success']:
            # LP失败,不充放电
            if i < len(issue_hours) - 1:
                next_h = issue_hours[i+1]
                n_exec = (next_h - issue_h) * 6
            else:
                n_exec = n_rest
            for k in range(n_exec):
                t = t_start + k
                demand_kWh = load_real[t] * DT
                pv_kWh = pv_real[t] * DT
                g_plan_mpc[t] = max(0.0, demand_kWh - pv_kWh)
                soc_exec[t+1] = soc_exec[t]
            continue
        
        if i < len(issue_hours) - 1:
            next_h = issue_hours[i+1]
            n_exec = (next_h - issue_h) * 6
        else:
            n_exec = n_rest
        
        g_exec_seg = sol['g'][:n_exec]
        c_exec_seg = sol['c'][:n_exec]
        d_exec_seg = sol['d'][:n_exec]
        
        for k in range(n_exec):
            t = t_start + k
            g_plan_mpc[t] = g_exec_seg[k]
            c_exec[t] = c_exec_seg[k]
            d_exec[t] = d_exec_seg[k]
            soc_exec[t+1] = soc_exec[t] + ETA * c_exec[t] - d_exec[t] / ETA
    
    # 结算
    supply = g_plan_mpc + pv_real * DT + d_exec - c_exec
    demand = load_real * DT
    e_mpc = np.maximum(0.0, demand - supply)
    
    plan_cost = float((price_day * g_plan_mpc).sum())
    emergency_cost = float((5.0 * price_day * e_mpc).sum())
    total_cost = plan_cost + emergency_cost
    
    daily_results.append({
        'date': str(date),
        'plan_cost': plan_cost,
        'emergency_cost': emergency_cost,
        'total_cost': total_cost,
        'plan_purchase': float(g_plan_mpc.sum()),
        'emergency_purchase': float(e_mpc.sum()),
        'charge': float(c_exec.sum()),
        'discharge': float(d_exec.sum())
    })
    
    if (day_idx - start_idx + 1) % 50 == 0:
        print(f"  已完成 {day_idx - start_idx + 1}/{n_days} 天")

print(f"\n成功求解 {len(daily_results)} 天")

# ========== 统计汇总 ==========
df_res = pd.DataFrame(daily_results)
total_plan = df_res['plan_cost'].sum()
total_emerg = df_res['emergency_cost'].sum()
total_all = df_res['total_cost'].sum()

print(f"\n{'='*60}")
print("全年汇总(2.1~12.31)")
print(f"{'='*60}")
print(f"计划购电成本: {total_plan:,.2f} 元")
print(f"紧急购电成本: {total_emerg:,.2f} 元")
print(f"总成本:       {total_all:,.2f} 元")
print(f"紧急购电占比: {100.0*total_emerg/total_all:.2f}%")
print(f"日均成本:     {total_all/len(daily_results):,.2f} 元/天")

# ========== 与问题2比较 ==========
try:
    with open(RES / "problem2.json", 'r', encoding='utf-8') as f:
        p2_data = json.load(f)
    p2_total = p2_data['summary']['total_cost']
    saving = p2_total - total_all
    saving_pct = 100.0 * saving / p2_total
    print(f"\n与问题2对比(固定电价+日前计划):")
    print(f"  问题2总成本: {p2_total:,.2f} 元")
    print(f"  问题4总成本: {total_all:,.2f} 元")
    print(f"  节省:        {saving:,.2f} 元 ({saving_pct:+.2f}%)")
except:
    print("\n未找到问题2结果,无法对比")

# ========== 导出Excel ==========
excel_path = RES / "result4.xlsx"
with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
    summary = pd.DataFrame({
        '指标': ['计划购电成本(元)', '紧急购电成本(元)', '总成本(元)',
                '计划购电量(kWh)', '紧急购电量(kWh)',
                '充电量(kWh)', '放电量(kWh)', '天数'],
        '数值': [total_plan, total_emerg, total_all,
                df_res['plan_purchase'].sum(), df_res['emergency_purchase'].sum(),
                df_res['charge'].sum(), df_res['discharge'].sum(), len(daily_results)]
    })
    summary.to_excel(writer, sheet_name='汇总', index=False)
    df_res.to_excel(writer, sheet_name='每日明细', index=False)

print(f"\n已保存: {excel_path}")

# ========== 导出JSON ==========
json_path = RES / "problem4.json"
with open(json_path, 'w', encoding='utf-8') as f:
    json.dump({
        'summary': {
            'plan_cost': float(total_plan),
            'emergency_cost': float(total_emerg),
            'total_cost': float(total_all),
            'n_days': len(daily_results)
        },
        'daily': daily_results
    }, f, indent=2, ensure_ascii=False)
print(f"已保存: {json_path}")

# ========== 绘图 ==========
print("\n生成图表...")
fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

dates_plot = pd.to_datetime(df_res['date'])
ax = axes[0]
ax.plot(dates_plot, df_res['total_cost'], label='总成本', color=PALETTE[0])
ax.plot(dates_plot, df_res['plan_cost'], label='计划成本', color=PALETTE[1], alpha=0.7)
ax.set_ylabel('成本 (元)')
ax.legend(loc='best')
ax.grid(True, alpha=0.3)

ax = axes[1]
ax.plot(dates_plot, df_res['emergency_purchase'], label='紧急购电量', color=PALETTE[2])
ax.set_ylabel('紧急购电 (kWh)')
ax.set_xlabel('日期')
ax.legend(loc='best')
ax.grid(True, alpha=0.3)

plt.tight_layout()
fig_path = FIG / "problem4.png"
plt.savefig(fig_path, dpi=300, bbox_inches='tight')
plt.close()
print(f"已保存: {fig_path}")

print(f"\n{'='*60}")
print("问题4求解完成!")
print(f"{'='*60}")
print(f"产物清单:")
print(f"  - 结果文件: {excel_path}")
print(f"  - JSON结果: {json_path}")
print(f"  - 主图: {fig_path}")
print(f"\n核心结论:")
print(f"  1. 全年总成本: {total_all:,.2f} 元({len(daily_results)}天)")
print(f"  2. 紧急购电成本: {total_emerg:,.2f} 元(占{100.0*total_emerg/total_all:.2f}%)")
print(f"  3. 日均成本: {total_all/len(daily_results):,.2f} 元/天")

"""问题2: 固定电价+日前计划+两阶段结算(2025.2.1 - 12.31共335天)"""
import matplotlib
matplotlib.use("Agg")
from pathlib import Path
import numpy as np
import pandas as pd
import json
import matplotlib.pyplot as plt
from plot_style import apply, PALETTE
from config import SEED, DT_HOUR, STEPS_PER_DAY, FILE_A1
from microgrid import (
    solve_window, load_price_fixed, load_daily_matrix,
    load_pv_forecast, interp_forecast_to_10min,
    SOC_INIT, DT, T
)

apply()
np.random.seed(SEED)

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "figures"
RES = ROOT / "results"
FIG.mkdir(exist_ok=True)
RES.mkdir(exist_ok=True)

print("="*60)
print("问题2: 固定电价 + 日前计划 + 两阶段结算")
print("="*60)

# ========== 数据加载 ==========
price_fixed = load_price_fixed()
dates_load, load_mat = load_daily_matrix('小区负载')
dates_pv, pv_mat = load_daily_matrix('光伏发电实际功率')
fc_dict = load_pv_forecast()

# 日期范围: 2.1(第31天,索引31) ~ 12.31(第364天,索引364), 共334天
# Python索引: dates[31]..dates[364], 即索引31..364(含),共334个
start_idx = 31  # 2月1日
end_idx = 364   # 12月31日
n_days = end_idx - start_idx + 1
print(f"模拟日期: {dates_load[start_idx]} ~ {dates_load[end_idx]}, 共 {n_days} 天")

# ========== 先顺序推演1月,确定2月1日初始SOC ==========
# 不人为指定2月1日SOC,而是从1月1日的初始SOC连续执行日前计划。
soc_current = SOC_INIT
for day_idx in range(0, start_idx):
    date = dates_load[day_idx]
    key = (date, 0)
    if key not in fc_dict:
        print(f"  警告: {date} 无0:00预报,1月状态保持不变")
        continue
    pv_forecast_jan = interp_forecast_to_10min(0, fc_dict[key])
    jan_sol = solve_window(
        price_fixed, load_mat[day_idx, :], pv_forecast_jan,
        soc_current, soc_final=None
    )
    if jan_sol['success']:
        soc_current = float(jan_sol['soc'][-1])
    else:
        print(f"  警告: {date} 1月状态推演失败,状态保持不变")
print(f"1月连续推演后的2月1日初始SOC: {soc_current:.2f} kWh")

# ========== 逐日两阶段求解 ==========
results = []
for day_idx in range(start_idx, end_idx + 1):
    date = dates_load[day_idx]
    
    # 0:00预报
    key = (date, 0)
    if key not in fc_dict:
        print(f"  警告: {date} 无0:00预报,跳过")
        continue
    fc24 = fc_dict[key]
    pv_forecast_kw = interp_forecast_to_10min(0, fc24)  # 0:10..24:00, 长度144
    
    # 第一阶段: 日前计划(用预报负载=实际负载,预报光伏,固定电价)
    load_plan_kw = load_mat[day_idx, :]
    soc_start = soc_current
    sol = solve_window(price_fixed, load_plan_kw, pv_forecast_kw,
                       soc_start, soc_final=None)
    
    if not sol['success']:
        print(f"  {date}: LP失败 {sol.get('message','')}")
        continue
    
    g_plan = sol['g']
    c_plan = sol['c']
    d_plan = sol['d']
    plan_cost = sol['cost']
    soc_current = float(sol['soc'][-1])
    
    # 第二阶段: 按计划充放电,用真实负载/光伏结算
    load_real_kw = load_mat[day_idx, :]
    pv_real_kw = pv_mat[day_idx, :]
    
    supply = g_plan + pv_real_kw * DT + d_plan - c_plan
    demand = load_real_kw * DT
    e = np.maximum(0.0, demand - supply)  # 紧急购电 kWh
    
    emergency_cost = float((5.0 * price_fixed * e).sum())
    total_cost = plan_cost + emergency_cost
    
    results.append({
        'date': str(date),
        'plan_cost': plan_cost,
        'emergency_cost': emergency_cost,
        'total_cost': total_cost,
        'plan_purchase': float(g_plan.sum()),
        'emergency_purchase': float(e.sum()),
        'charge': float(c_plan.sum()),
        'discharge': float(d_plan.sum()),
        'soc_start': soc_start,
        'soc_end': soc_current
    })
    
    if (day_idx - start_idx + 1) % 50 == 0:
        print(f"  已完成 {day_idx - start_idx + 1}/{n_days} 天")

print(f"\n成功求解 {len(results)} 天")

# ========== 统计汇总 ==========
df_res = pd.DataFrame(results)
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
print(f"日均成本:     {total_all/len(results):,.2f} 元/天")

# ========== 导出Excel ==========
excel_path = RES / "result2.xlsx"
with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
    # 汇总表
    summary = pd.DataFrame({
        '指标': ['计划购电成本(元)', '紧急购电成本(元)', '总成本(元)',
                '计划购电量(kWh)', '紧急购电量(kWh)',
                '充电量(kWh)', '放电量(kWh)', '天数'],
        '数值': [total_plan, total_emerg, total_all,
                df_res['plan_purchase'].sum(), df_res['emergency_purchase'].sum(),
                df_res['charge'].sum(), df_res['discharge'].sum(), len(results)]
    })
    summary.to_excel(writer, sheet_name='汇总', index=False)
    
    # 每日明细
    df_res.to_excel(writer, sheet_name='每日明细', index=False)

print(f"\n已保存: {excel_path}")

# ========== 导出JSON ==========
json_path = RES / "problem2.json"
with open(json_path, 'w', encoding='utf-8') as f:
    json.dump({
        'summary': {
            'plan_cost': float(total_plan),
            'emergency_cost': float(total_emerg),
            'total_cost': float(total_all),
            'n_days': len(results)
        },
        'daily': results
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
fig_path = FIG / "problem2.png"
plt.savefig(fig_path, dpi=300, bbox_inches='tight')
plt.close()
print(f"已保存: {fig_path}")

print(f"\n{'='*60}")
print("问题2求解完成!")
print(f"{'='*60}")
print(f"产物清单:")
print(f"  - 结果文件: {excel_path}")
print(f"  - JSON结果: {json_path}")
print(f"  - 主图: {fig_path}")
print(f"\n核心结论:")
print(f"  1. 全年总成本: {total_all:,.2f} 元({len(results)}天)")
print(f"  2. 紧急购电成本: {total_emerg:,.2f} 元(占{100.0*total_emerg/total_all:.2f}%)")
print(f"  3. 日均成本: {total_all/len(results):,.2f} 元/天")

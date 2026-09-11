"""微网储能调度 - 共享LP求解引擎(供问题1/2/3/4复用)"""
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from config import DT_HOUR, STEPS_PER_DAY, FILE_A1, FILE_A2, FILE_A3, FILE_A4

# ========== 题目储能参数(全项目统一) ==========
E_CAP = 12000.0
P_MAX = 5000.0
ETA = 0.9
SOC_MIN = 1200.0
SOC_MAX = 10800.0
SOC_INIT = 6000.0
DT = DT_HOUR
T = STEPS_PER_DAY
C_MAX = P_MAX * DT


def solve_window(price, load_kw, pv_kw, soc_start, soc_final=None,
                 dt=DT, cmax=C_MAX, eta=ETA,
                 soc_min=SOC_MIN, soc_max=SOC_MAX):
    """求解时间窗口的购电-储能LP。返回 dict(g,c,d,soc,cost,success)。"""
    price = np.asarray(price, float)
    load_kw = np.asarray(load_kw, float)
    pv_kw = np.asarray(pv_kw, float)
    n = len(price)
    n_vars = 4 * n
    idx_g = np.arange(0, n)
    idx_c = np.arange(n, 2 * n)
    idx_d = np.arange(2 * n, 3 * n)
    idx_soc = np.arange(3 * n, 4 * n)
    cvec = np.zeros(n_vars)
    cvec[idx_g] = price
    bounds = ([(0, None)] * n + [(0, cmax)] * n
              + [(0, cmax)] * n + [(None, None)] * n)
    rows_ub, b_ub = [], []
    for t in range(n):
        r = np.zeros(n_vars)
        r[idx_g[t]] = -1.0
        r[idx_c[t]] = 1.0
        r[idx_d[t]] = -1.0
        rows_ub.append(r)
        b_ub.append((pv_kw[t] - load_kw[t]) * dt)
    for t in range(n):
        r = np.zeros(n_vars)
        r[idx_soc[t]] = -1.0
        rows_ub.append(r)
        b_ub.append(-soc_min)
    for t in range(n):
        r = np.zeros(n_vars)
        r[idx_soc[t]] = 1.0
        rows_ub.append(r)
        b_ub.append(soc_max)
    A_ub = np.array(rows_ub)
    b_ub = np.array(b_ub)
    rows_eq, b_eq = [], []
    for t in range(n):
        r = np.zeros(n_vars)
        r[idx_soc[t]] = 1.0
        r[idx_c[t]] = -eta
        r[idx_d[t]] = 1.0 / eta
        if t == 0:
            b_eq.append(soc_start)
        else:
            r[idx_soc[t - 1]] = -1.0
            b_eq.append(0.0)
        rows_eq.append(r)
    if soc_final is not None:
        r = np.zeros(n_vars)
        r[idx_soc[n - 1]] = 1.0
        rows_eq.append(r)
        b_eq.append(soc_final)
    A_eq = np.array(rows_eq)
    b_eq = np.array(b_eq)
    res = linprog(cvec, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                  bounds=bounds, method='highs')
    if not res.success:
        return {'success': False, 'message': res.message}
    x = res.x
    return {'success': True, 'g': x[idx_g], 'c': x[idx_c],
            'd': x[idx_d], 'soc': x[idx_soc], 'cost': float(res.fun)}


def load_price_fixed():
    df = pd.read_excel(FILE_A1, sheet_name='Sheet1')
    return df['电价'].values.astype(float)


def load_daily_matrix(sheet):
    df = pd.read_excel(FILE_A2, sheet_name=sheet)
    dates = pd.to_datetime(df.iloc[:, 0]).dt.date.values
    mat = df.iloc[:, 1:].values.astype(float)
    return dates, mat


def load_price_volatile():
    df = pd.read_excel(FILE_A4, sheet_name='Sheet1')
    dates = pd.to_datetime(df.iloc[:, 0]).dt.date.values
    mat = df.iloc[:, 1:].values.astype(float)
    return dates, mat


def load_pv_forecast():
    df = pd.read_excel(FILE_A3, sheet_name='Sheet1')
    df['日期'] = df['日期'].ffill()
    fc = {}
    for _, row in df.iterrows():
        d = pd.to_datetime(row['日期']).date()
        hour = int(str(row['预报时刻']).strip().split(':')[0])
        vals = row[[f'预报{h}小时' for h in range(1, 25)]].values.astype(float)
        fc[(d, hour)] = vals
    return fc


def interp_forecast_to_10min(issue_hour, fc24, anchor_val=0.0):
    anchor_h = np.arange(issue_hour, issue_hour + 25)
    anchor_v = np.concatenate([[anchor_val], fc24])
    n_rest = (24 - issue_hour) * 6
    target_h = issue_hour + np.arange(1, n_rest + 1) * (10.0 / 60.0)
    vals = np.interp(target_h, anchor_h, anchor_v)
    return np.clip(vals, 0.0, None)


if __name__ == '__main__':
    print("=== 引擎自检: 复现问题1 ===")
    price = load_price_fixed()
    df1 = pd.read_excel(FILE_A1, sheet_name='Sheet1')
    load = df1['小区负载'].values.astype(float)
    pv = df1['光伏发电预测功率'].values.astype(float)
    sol = solve_window(price, load, pv, SOC_INIT, SOC_INIT)
    assert sol['success']
    print(f"全天购电费: {sol['cost']:.2f} 元 (应≈35126.95)")
    print(f"末态SOC: {sol['soc'][-1]:.2f} kWh (应=6000)")
    supply = sol['g'] + pv * DT + sol['d'] - sol['c']
    print(f"最大供电缺口: {(load * DT - supply).max():.6e} kWh")
    print("\n=== 数据加载自检 ===")
    dates, load_mat = load_daily_matrix('小区负载')
    print(f"附件2负载: {load_mat.shape}, {dates[0]} ~ {dates[-1]}")
    _, pv_mat = load_daily_matrix('光伏发电实际功率')
    print(f"附件2光伏: {pv_mat.shape}")
    pdates, pmat = load_price_volatile()
    print(f"附件4电价: {pmat.shape}, 均值 {pmat.mean():.4f}")
    fc = load_pv_forecast()
    print(f"附件3预报: {len(fc)} 条 (应=1460)")
    import datetime as dtm
    key = (dtm.date(2025, 6, 21), 6)
    if key in fc:
        rest = interp_forecast_to_10min(6, fc[key])
        print(f"6.21 6:00预报插值: 长度{len(rest)}(应108), 峰值{rest.max():.1f}")
    print("\n引擎自检通过!")

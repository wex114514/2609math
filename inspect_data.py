"""查看附件2/3/4数据结构"""
import pandas as pd
from config import FILE_A2, FILE_A3, FILE_A4

for f, name in [(FILE_A2, "附件2"), (FILE_A3, "附件3"), (FILE_A4, "附件4")]:
    print(f"\n{'='*70}\n{name}: {f}\n{'='*70}")
    xls = pd.ExcelFile(f)
    print(f"工作表: {xls.sheet_names}")
    for sh in xls.sheet_names:
        df = pd.read_excel(f, sheet_name=sh)
        print(f"\n--- 工作表[{sh}] shape={df.shape} ---")
        print(f"列名(前5): {list(df.columns)[:5]} ... 共{len(df.columns)}列")
        print(f"末列: {list(df.columns)[-3:]}")
        print(df.iloc[:3, :6])
        print(f"...\n最后几行:\n{df.iloc[-3:, :6]}")

# -*- coding: utf-8 -*-
"""拉申万三级行业成分,映射回二级行业,输出 industry_map.csv (code,industry)。
东财 push2 行情域不稳(SOP 坑1),故用国证 legs 域的申万接口。用法:python industry_map.py sw"""
import sys, io, os, time
os.environ.setdefault("TQDM_DISABLE", "1")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd
import akshare as ak

if __name__ == "__main__":
    third = ak.sw_index_third_info()  # 行业代码,行业名称,上级行业(二级)
    m = {}
    for i, r in third.iterrows():
        code2, name2 = r["上级行业"], r["上级行业"]
        for t in range(3):
            try:
                cons = ak.sw_index_third_cons(symbol=r["行业代码"])
                for c in cons["股票代码"].astype(str).str.zfill(6):
                    m[c] = f'{r["上级行业"]}/{r["行业名称"]}'
                break
            except Exception as e:
                if t == 2:
                    print(f"# sw skip {r['行业名称']}: {e}", file=sys.stderr)
                time.sleep(2)
        if i % 30 == 0:
            print(f"# sw {i}/{len(third)} 已映射{len(m)}", file=sys.stderr)
            pd.Series(m, name="industry").rename_axis("code").to_csv("industry_map.csv", encoding="utf-8-sig")
    pd.Series(m, name="industry").rename_axis("code").to_csv("industry_map.csv", encoding="utf-8-sig")
    print(f"# 完成 {len(m)} 只")

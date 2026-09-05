# -*- coding: utf-8 -*-
"""行业映射工具(2026-09-05 踩坑后固化的可用组合拳):
1. 新浪行业 spot+detail(~50 行业,约 3000 只,主板全)  -- 东财 push2 板块域断连不可用
2. 东财 datacenter 域 F10 RPT_F10_BASIC_ORGINFO(EM2016) 逐只补 688/301/新股缺口
   -- datacenter 域与 push2 行情域不同,是通的;别碰 push2
不可用已验证:akshare 1.18.94 无同花顺成分接口;申万 sw_index_third_cons 全市场拉取需数小时。
用法: python industry_map.py <codes.txt>   # 每行一个6位代码,输出 {code}\t行业 打印+industry_map.csv
      无参数时全量跑新浪层。
"""
import sys, io, os, time
os.environ.setdefault("TQDM_DISABLE", "1")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd
import requests
import akshare as ak

F10 = "https://datacenter.eastmoney.com/securities/api/data/v1/get"


def sec_suffix(c):
    if c.startswith(("60", "68")):
        return c + ".SH"
    if c.startswith(("83", "87", "43", "92")):
        return c + ".BJ"
    return c + ".SZ"


def sina_map():
    m = {}
    secs = ak.stock_sector_spot(indicator="新浪行业")
    for _, r in secs.iterrows():
        for t in range(2):
            try:
                d = ak.stock_sector_detail(sector=r["label"])
                for c in d["code"].astype(str).str.zfill(6):
                    m[c] = r["板块"]
                break
            except Exception:
                time.sleep(2)
    return m


def f10_industry(codes):
    out = {}
    for c in codes:
        for t in range(3):
            try:
                p = {"reportName": "RPT_F10_BASIC_ORGINFO", "columns": "SECURITY_CODE,EM2016",
                     "filter": f'(SECUCODE="{sec_suffix(c)}")', "pageSize": 1,
                     "source": "HSF10", "client": "PC"}
                d = requests.get(F10, params=p, timeout=10).json()
                data = (d.get("result") or {}).get("data") or []
                if data and data[0].get("EM2016"):
                    out[c] = data[0]["EM2016"]
                break
            except Exception:
                if t == 2:
                    print(f"# F10 miss {c}", file=sys.stderr)
                time.sleep(2)
    return out


if __name__ == "__main__":
    m = sina_map()
    print(f"# 新浪层覆盖 {len(m)} 只", file=sys.stderr)
    if len(sys.argv) > 1:
        codes = [l.strip() for l in open(sys.argv[1], encoding="utf-8") if l.strip().isdigit()]
        gap = [c for c in codes if c not in m]
        if gap:
            print(f"# F10 补 {len(gap)} 只缺口", file=sys.stderr)
            m.update(f10_industry(gap))
        miss = [c for c in codes if c not in m]
        print(f"# 目标 {len(codes)},未覆盖 {len(miss)} {miss}", file=sys.stderr)
        res = pd.Series({c: m.get(c, "") for c in codes}, name="industry").rename_axis("code")
    else:
        res = pd.Series(m, name="industry").rename_axis("code")
    res.to_csv("industry_map.csv", encoding="utf-8-sig")
    print(res.to_string())

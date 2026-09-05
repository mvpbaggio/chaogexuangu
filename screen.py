# -*- coding: utf-8 -*-
"""Serenity 全市场粗筛 v3(单请求,秒级):腾讯全A快照 -> 市值/换手/估算成交额 -> 候选池。
金额估算 = volume(手)*100*price(元),与腾讯日线 amount 同源同口径,无需逐只拉历史。
用法:python screen.py [最小市值亿] [最大市值亿] [最小换手%]
输出:candidates.csv + stdout
"""
import os, sys, io
os.environ.setdefault("TQDM_DISABLE", "1")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import akshare as ak
import pandas as pd

MIN_MC = float(sys.argv[1]) if len(sys.argv) > 1 else 30
MAX_MC = float(sys.argv[2]) if len(sys.argv) > 2 else 150
MIN_HSL = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
MIN_AMT = 5000.0  # 万元


def main():
    spot = ak.stock_zh_a_spot_tx()
    # 列名本就是 code/name/zsz/hsl/zxj/volume,无需 rename
    spot["code"] = spot["code"].str.replace(r"^(sh|sz|bj)", "", regex=True)
    spot = spot[spot["code"].str.match(r"^(60|00|30|68)\d{4}$")]
    spot = spot[~spot["name"].str.contains("ST|退", na=False)]
    spot["mktcap"] = pd.to_numeric(spot["zsz"], errors="coerce")
    spot["hsl"] = pd.to_numeric(spot["hsl"], errors="coerce")
    spot["price"] = pd.to_numeric(spot["zxj"], errors="coerce")
    spot["volume"] = pd.to_numeric(spot["volume"], errors="coerce")
    spot["est_amt万"] = (spot["volume"] * 100 * spot["price"] / 1e4).round(0)
    spot = spot[(spot["mktcap"] >= MIN_MC) & (spot["mktcap"] <= MAX_MC)]
    spot = spot[spot["hsl"] >= MIN_HSL]
    spot = spot[spot["est_amt万"] >= MIN_AMT]
    spot = spot.sort_values("est_amt万", ascending=False)

    out = spot[["code", "name", "price", "mktcap", "hsl", "est_amt万"]].copy()
    out["mktcap亿"] = out["mktcap"].round(2)
    out = out.drop(columns=["mktcap"]).rename(columns={"est_amt万": "估算日额万"})
    print(f"# 候选池(市值{MIN_MC}-{MAX_MC}亿, 换手>={MIN_HSL}%, 估算日额>={MIN_AMT}万): {len(out)} 只")
    out.to_csv("candidates.csv", index=False)
    print(out.head(40).to_string(index=False))
    if len(out) > 40:
        print(f"…共 {len(out)} 只, 完整名单见 candidates.csv")


if __name__ == "__main__":
    main()
# -*- coding: utf-8 -*-
"""Serenity 数据层:用 akshare 拉取四步筛选需要的量化指标。
用法:
  python check.py 600519            # 第二步+第三步量化指标 JSON
  python check.py 600519 --hist     # 附带近 60 日行情
数据源:财务三大表/研报=东方财富(报告期累计值,单季值由相邻报告期差分);
行情=腾讯(东财 push2 行情接口不稳定,腾讯源为主)。
"""
import os
os.environ.setdefault("TQDM_DISABLE", "1")
import argparse
import json
import sys
import time
from functools import lru_cache

import akshare as ak
import pandas as pd


def retry(fn, name: str, attempts: int = 3):
    """接口偶发断连/限流,指数退避重试。"""
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            if i == attempts - 1:
                raise RuntimeError(f"{name} 重试{attempts}次仍失败: {e!r}") from e
            time.sleep(3 * (i + 1))


# ponytail: 全池批跑时同一只股票的 step2/step3 会各拉一次同一张报表,lru_cache 复用
# 少一半东财请求;内存上限 128 条,批跑顺序访问不会积压
@lru_cache(maxsize=128)
def _profit(em: str):
    return retry(lambda: ak.stock_profit_sheet_by_report_em(symbol=em), "利润表")


@lru_cache(maxsize=128)
def _cash(em: str):
    return retry(lambda: ak.stock_cash_flow_sheet_by_report_em(symbol=em), "现金流量表")


@lru_cache(maxsize=128)
def _balance(em: str):
    return retry(lambda: ak.stock_balance_sheet_by_report_em(symbol=em), "资产负债表")


@lru_cache(maxsize=128)
def _hist(tx: str):
    return retry(lambda: ak.stock_zh_a_hist_tx(symbol=tx), "腾讯行情")


def tx_symbol(code: str) -> str:
    return ("sh" if code.startswith(("6", "9")) else
            "bj" if code.startswith(("4", "8")) else "sz") + code


def em_symbol(code: str) -> str:
    return ("SH" if code.startswith(("6", "9")) else
            "BJ" if code.startswith(("4", "8")) else "SZ") + code


def q_single(df: pd.DataFrame, col: str) -> pd.Series:
    """累计值 -> 单季度值(第一个报告期保持原值)。REPORT_DATE 升序。"""
    s = df[col].astype(float)
    return s.diff().fillna(s)


def have(df: pd.DataFrame, col: str) -> bool:
    return col in df.columns


def step2_fin(symbol: str) -> dict:
    """第二步:财务拐点指标,近 5 个报告期(足够算 4 期环比/同比)。
    ponytail: 金融类公司(银行/券商/保险)利润表没有"营业成本"(OPERATE_COST),
    用"营业支出"(OPERATE_EXPENSE),且无在建工程等制造业指标。缺失字段一律标
    "待核实(字段缺失)"不阻塞,由调用方决定该行业是否适配本框架。
    """
    em = em_symbol(symbol)
    # 东财报表按报告期新→旧返回,必须先升序排序再 tail,否则拿到的是最老报告期
    profit = _profit(em)
    cash = _cash(em)
    balance = _balance(em)
    for df in (profit, cash, balance):
        df["REPORT_DATE"] = pd.to_datetime(df["REPORT_DATE"]).dt.strftime("%Y-%m-%d")
        df.sort_values("REPORT_DATE", inplace=True)
    profit, cash, balance = profit.tail(9), cash.tail(9), balance.tail(9)

    # 毛利率 = (营业收入-营业成本)/营业收入,单季度口径;金融类无 OPERATE_COST -> 待核实
    rev_q = q_single(profit, "OPERATE_INCOME") if have(profit, "OPERATE_INCOME") else pd.Series(dtype=float)
    if have(profit, "OPERATE_COST"):
        gm_q = ((rev_q - q_single(profit, "OPERATE_COST")) / rev_q * 100).round(2)
    else:
        gm_q = pd.Series(dtype=float)
    capex_q = (q_single(cash, "CONSTRUCT_LONG_ASSET")
               if have(cash, "CONSTRUCT_LONG_ASSET") else pd.Series(dtype=float))
    ocf_ratio = (cash["NETCASH_OPERATE"].astype(float)
                 / profit["PARENT_NETPROFIT"].astype(float)).round(2)
    contract = (balance["CONTRACT_LIAB"].astype(float)
                if have(balance, "CONTRACT_LIAB") else pd.Series(dtype=float))
    # 在建工程字段(东财版本漂移:CIP / CONSTRUCT_IN_PROCESS)
    cip_col = next((c for c in ("CIP", "CONSTRUCT_IN_PROCESS") if c in balance.columns), None)
    if cip_col:
        cip_yoy = balance.set_index("REPORT_DATE")[cip_col].pct_change(4).mul(100).round(2)
    else:
        cip_yoy = pd.Series(dtype=float)

    rows = []
    for i in range(-4, 0):
        d = profit["REPORT_DATE"].iloc[i]
        rows.append({
            "报告期": d,
            "单季毛利率%": gm_q.iloc[i] if not gm_q.empty else None,
            "单季CapEx(万)": round(capex_q.iloc[i] / 1e4, 1) if not capex_q.empty and pd.notna(capex_q.iloc[i]) else None,
            "在建工程同比%": cip_yoy.get(d) if not cip_yoy.empty else None,
            "累计OCF/净利润": ocf_ratio.iloc[i] if not ocf_ratio.empty else None,
            "合同负债(万)": round(contract.iloc[i] / 1e4, 1) if not contract.empty else None,
        })
    na = pd.isna
    def chk(cond):
        return bool(cond) if cond is not None and not isinstance(cond, str) else cond
    verdict = {
        "①毛利率连续2季环比升": ("待核实(无营业成本字段,或数据不足)" if gm_q.empty
                             else bool(gm_q.iloc[-1] > gm_q.iloc[-2] > gm_q.iloc[-3])),
        "②CapEx连续2季环比增": ("待核实(CapEx字段缺失)" if capex_q.empty
                            else bool(capex_q.iloc[-1] > capex_q.iloc[-2] > capex_q.iloc[-3])),
        "②在建工程同比≥30%": ("待核实(字段缺失)" if cip_yoy.empty or na(cip_yoy.iloc[-1])
                             else bool(cip_yoy.iloc[-1] >= 30)),
        "③OCF/净利润≥0.8": ("待核实(净利为负,比值无意义)" if profit["PARENT_NETPROFIT"].iloc[-1] <= 0
                           else ("待核实(数据缺失)" if ocf_ratio.empty or na(ocf_ratio.iloc[-1])
                                 else bool(ocf_ratio.iloc[-1] >= 0.8))),
        "④合同负债连续2季环比增": ("待核实(字段缺失)" if contract.empty
                             else bool(contract.iloc[-1] > contract.iloc[-2] > contract.iloc[-3])),
    }
    return {"报告期数据": rows, "验证判定": verdict}


def step3_market(symbol: str) -> dict:
    """第三步:市值 / 流动性(腾讯快照资金流,批跑稳定) / 券商评级覆盖度。"""
    hist = _hist(tx_symbol(symbol))
    close = float(hist["close"].iloc[-1])
    shares = float(_balance(em_symbol(symbol)).sort_values("REPORT_DATE")["SHARE_CAPITAL"].iloc[-1])
    avg_amount = float(hist["amount"].tail(20).mean())  # 元
    try:
        research = retry(lambda: ak.stock_research_report_em(symbol=symbol), "研报")
        research["日期"] = pd.to_datetime(research["日期"])
        ratings_3m = int((research["日期"] >= pd.Timestamp.now() - pd.DateOffset(months=3)).sum())
    except Exception as e:
        ratings_3m = f"获取失败: {e}"
    return {
        "总市值(亿)": round(close * shares / 1e8, 2),
        "股价": close,
        "近20日日均成交额(万)": round(avg_amount / 1e4, 1),
        "近3个月券商研报篇数": ratings_3m,
        "数据日期": str(hist["date"].iloc[-1]),
        "备注": "研报篇数≠评级家数(同家机构多篇会重复计),精确评级家数待人工核实;行业/市占率由分析环节补充",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol", help="6 位 A 股代码,如 600519")
    ap.add_argument("--hist", action="store_true", help="附带近 60 日行情")
    args = ap.parse_args()

    out = {"代码": args.symbol,
           "第二步_财务拐点": step2_fin(args.symbol),
           "第三步_市场指标": step3_market(args.symbol)}
    if args.hist:
        hist = retry(lambda: ak.stock_zh_a_hist_tx(symbol=tx_symbol(args.symbol)), "腾讯行情").tail(60)
        out["近60日行情"] = json.loads(hist.to_json(orient="records", force_ascii=False))
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

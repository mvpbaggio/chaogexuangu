# -*- coding: utf-8 -*-
"""Serenity 全市场第二步财务验证(批量版):
东财按报告期全市场三表(stock_lrb_em/zcfz_em/xjll_em)各拉 5 期,
向量化计算 2355 只候选的财务拐点判定,代替逐股调用(39h -> ~3min)。
口径标注(vs check.py 逐股版):
  ①毛利率: (营业总收入-营业支出)/营业总收入,单季差分 —— 同原版
  ②CapEx:  批量现金流量表无"购建固定资产"细分,代理口径假阳性率 14/15(2026-09-05
           实测),**已降为参考列不计分** —— 晋级看 ①③④ 全过,②仅供人工参考
  ③OCF/净利润: 累计口径 —— 同原版
  ④合同负债: 用"预收账款"代理(东财汇总表未细分) —— 标注
  净利同比: lrb 自带列,直接输出,二次确认不依赖外部脚本
晋级规则(2026-09-05 校准): ①③④ 全过=晋级;
  观察=③过 + 净利同比≥30% + ①/④至少1项过(强在建型标的盲区补位);
  其余淘汰。用法:python batch_check2.py   输出 full_screen_results.csv
"""
import os, sys, io, time
from datetime import date
os.environ.setdefault("TQDM_DISABLE", "1")
# 幂等包装:已被包过/已是 utf-8 时不要再包,否则旧 wrapper 被 GC 会关闭底层 buffer,
# 模块将无法被 import(如 selftest/调度器复用 last_report_dates)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import akshare as ak
import pandas as pd


def last_report_dates(n=5, today=None):
    """最近 n 个已披露完毕的报告期(YYYYMMDD,升序)。
    披露截止:Q1+30d / 半年报+62d / Q3+31d / 年报+120d;未到截止的季度不取,
    否则差分链上出现大面积缺报,判定会静默劣化成'?'。"""
    today = today or date.today()
    deadlines = {3: 30, 6: 62, 9: 31, 12: 120}
    ends = []
    y = today.year
    while len(ends) < n:
        for m in (12, 9, 6, 3):
            d = date(y, m, {3: 31, 6: 30, 9: 30, 12: 31}[m])
            if d <= today and (today - d).days >= deadlines[m]:
                ends.append(d)
        y -= 1
    return [d.strftime("%Y%m%d") for d in sorted(ends[:n])]


# 5 个报告期(累计值),差分出最近 4 个单季
DATES = last_report_dates(5)


def retry(fn, name, n=3):
    for i in range(n):
        try:
            return fn()
        except Exception as e:
            if i == n - 1:
                raise RuntimeError(f"{name}: {e!r}")
            print(f"# {name} retry {i+1}", file=sys.stderr)
            time.sleep(5)


def fetch_all():
    out = {}
    for api, key in [(ak.stock_lrb_em, "lrb"), (ak.stock_zcfz_em, "zcfz"), (ak.stock_xjll_em, "xjll")]:
        for d in DATES:
            df = retry(lambda a=api, dd=d: a(date=dd), f"{key}{d}")
            df["股票代码"] = df["股票代码"].astype(str).str.zfill(6)
            out[(key, d)] = df.set_index("股票代码")
            print(f"# {key} {d}: {len(df)} 行", file=sys.stderr)
    return out


def main():
    data = fetch_all()

    def series(key, col):
        return pd.DataFrame({d: data[(key, d)][col] for d in DATES})

    rev = series("lrb", "营业总收入").astype(float)
    cost = series("lrb", "营业总支出-营业支出").astype(float)
    profit = series("lrb", "净利润").astype(float)
    prepay = series("zcfz", "负债-预收账款").astype(float)
    ocf = series("xjll", "经营性现金流-现金流量净额").astype(float)
    inv = series("xjll", "投资性现金流-现金流量净额").astype(float)

    # 单季差分:累计序列 H1->Q3->FY->Q1->H1 中,Q1 报告本身就是单季值,
    # 差分(Q1-年报)得负数、负负得正出伪毛利率(实测 99.8% 标的被此 bug 污染)。
    # 规则:3 月末报告期保持原值,其余列=本期累计-上期累计;中间缺报保持 NaN。
    def q_single(df):
        d = df.diff(axis=1)
        d.iloc[:, 0] = df.iloc[:, 0]
        q1_cols = [c for c in df.columns if c.endswith("0331")]
        for c in q1_cols:
            d[c] = df[c]
        return d

    gm = ((q_single(rev) - q_single(cost)) / q_single(rev) * 100)
    gm = gm.mask(q_single(rev) <= 0)  # 单季营收≤0 时毛利率无意义
    capex = -q_single(inv)  # 投资净流出为正
    capex = capex.where(capex.abs() < 1e15)  # 剔除极端异常值

    rows = []
    cands = pd.read_csv("candidates.csv", dtype={"code": str})
    for _, c in cands.iterrows():
        code = c["code"]
        try:
            g3 = [gm.loc[code, DATES[2]], gm.loc[code, DATES[3]], gm.loc[code, DATES[4]]]
            # DATES 升序,g3=[旧,中,新];"连续2季环比升"= 新>中>旧
            v1 = bool(g3[2] > g3[1] > g3[0]) if all(pd.notna(g3)) else "?"
            k3 = [capex.loc[code, DATES[2]], capex.loc[code, DATES[3]], capex.loc[code, DATES[4]]]
            # ②CapEx 代理假阳性率 14/15,不计分,仅输出参考
            v2ref = bool(k3[2] > k3[1] > k3[0]) if all(pd.notna(k3)) else "?"
            np_ = profit.loc[code, DATES[4]]
            v3 = ("?" if (pd.isna(np_) or np_ <= 0)  # 净利为负时 OCF/净利 比值无意义
                  else bool(ocf.loc[code, DATES[4]] / np_ >= 0.8))
            p3 = [prepay.loc[code, DATES[2]], prepay.loc[code, DATES[3]], prepay.loc[code, DATES[4]]]
            v4 = bool(p3[2] > p3[1] > p3[0]) if all(pd.notna(p3)) else "?"
            npyoy = data[("lrb", DATES[4])].loc[code, "净利润同比"] if "净利润同比" in data[("lrb", DATES[4])].columns else None
            yoy_ok = isinstance(npyoy, (int, float)) and not pd.isna(npyoy)
            # 计分判定项=①③④(②代理不计分);全过=晋级
            core = (v1, v3, v4)
            passed = sum(1 for x in core if x is True)
            # 观察档(加严):③过 + 净利同比≥30% + ①/④至少1项过 —— 强在建型盲区补位
            # SOP 二次确认:净利同比<0 直接判伪拐点,即使①③④全过(SOP:净利为负时③标待核实)
            if passed == 3 and yoy_ok and npyoy < 0:
                grade = "伪拐点(净利同比<0)"
            elif passed == 3:
                grade = "晋级"
            elif v3 is True and yoy_ok and npyoy >= 30 and (v1 is True or v4 is True):
                grade = "观察"
            else:
                grade = "淘汰"
            rows.append([code, c["name"], c["mktcap亿"], c["估算日额万"],
                         str(v1), str(v2ref), "?", str(v3), str(v4), passed,
                         npyoy if yoy_ok else "", grade])
        except KeyError:
            rows.append([code, c["name"], c["mktcap亿"], c["估算日额万"],
                         "?", "?", "?", "?", "?", 0, "缺报告期数据"])

    out = pd.DataFrame(rows, columns=["code", "name", "mktcap亿", "日额万",
                                      "①毛利率升", "②CapEx增(参考不计分)", "②在建同比(待核实)",
                                      "③OCF/净利", "④预收增(代理)", "通过项数(①③④)", "净利同比%", "备注"])
    out.sort_values("通过项数(①③④)", ascending=False).to_csv("full_screen_results.csv", index=False, encoding="utf-8-sig")
    print(f"# 完成 {len(out)} 只; ①③④全过(晋级): {(out['通过项数(①③④)']>=3).sum()} 只; 观察: {(out['备注']=='观察').sum()} 只")
    print(out[out["通过项数(①③④)"] >= 3].to_string(index=False))


if __name__ == "__main__":
    main()
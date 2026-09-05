# -*- coding: utf-8 -*-
"""Serenity 第三步画像剔除(工具化):给 full_screen_results.csv 的晋级+观察档
贴行业、按画像关键词剔除消费/牌照/地产/公用/软件/农业等,输出 pool_candidates.csv
供人工/LLM 终审。行业来源:industry_sina.csv + 东财 F10 datacenter 域补缺。
用法:python build_pool.py [full_screen_results.csv]"""
import sys, io, os, time, re
os.environ.setdefault("TQDM_DISABLE", "1")
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd
import requests

SRC = sys.argv[1] if len(sys.argv) > 1 else "full_screen_results.csv"
OUT = "pool_candidates.csv"
SINA = "industry_sina.csv"

# 画像剔除关键词(匹配行业字符串;与 serenity-analyst.md 第三步口径一致)
EXCLUDE = [
    (r"银行|证券|保险|信托|租赁|多元金融", "牌照/金融"),
    (r"食品|饮料|酿酒|白酒|乳品|调味|零食", "消费-食饮"),
    (r"服装|鞋|纺织|家纺|珠宝|家具|家居|日用化学品|化妆品|个护|美容", "消费-轻工"),
    (r"酒店|旅游|餐饮|教育|传媒|影视|游戏|营销|出版|互联网", "消费-服务"),
    (r"零售|百货|商贸|商业物业|贸易|专业市场", "零售/贸易"),
    (r"房地产|物业", "地产"),
    (r"电力|供水|供气|燃气|水务|环保", "公用/环保"),
    (r"软件|信息技术服务|计算机设备|通信服务|云计算|数字营销", "软件/IT服务"),
    (r"农林牧渔|种植|养殖|渔业|农药|化肥|饲料|动物保健", "农业"),
    (r"煤炭|石油|天然气开采|贵金属|黄金|采掘|焦炭", "周期-资源"),
    (r"CXO|生物医药|医疗研发外包|医疗服务|诊断|医药商业|医药流通|中药", "医药-服务/流通"),
]
KEEP_HINT = r"半导体|集成电路|芯片|电子化学品|磁性|传感|伺服|光学|膜|射频|微波|功率|EDA|检测|机床|减速|丝杠|轴承|密封|航空|航天|军工|芳纶|复材|工程塑料|特种|封装|面板|电池结构|储能|配电|特高压"


def sec_suffix(c):
    if c.startswith(("60", "68")):
        return c + ".SH"
    if c.startswith(("83", "87", "43", "92")):
        return c + ".BJ"
    return c + ".SZ"


def load_industry(codes):
    """行业来源优先级:F10 EM2016(细粒度,如 医药生物-医疗服务-医疗服务,关键词才咬得住)
    > 新浪行业(粗粒度兜底)。"""
    m = {}
    if os.path.exists(SINA):
        m = pd.read_csv(SINA, dtype={"code": str}).set_index("code")["industry"].to_dict()
    url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    for c in codes:
        for t in range(3):
            try:
                p = {"reportName": "RPT_F10_BASIC_ORGINFO", "columns": "SECURITY_CODE,EM2016",
                     "filter": f'(SECUCODE="{sec_suffix(c)}")', "pageSize": 1,
                     "source": "HSF10", "client": "PC"}
                data = ((requests.get(url, params=p, timeout=10).json().get("result") or {}).get("data") or [])
                if data and data[0].get("EM2016"):
                    m[c] = data[0]["EM2016"]
                break
            except Exception:
                if t == 2:
                    print(f"# 行业缺失 {c}", file=sys.stderr)
                time.sleep(2)
    return m


def judge(industry):
    for pat, why in EXCLUDE:
        if re.search(pat, industry or ""):
            return f"剔除({why})"
    if re.search(KEEP_HINT, industry or ""):
        return "保留(技术瓶颈画像)"
    return "保留(画像中性,人工终审)"


if __name__ == "__main__":
    d = pd.read_csv(SRC, dtype={"code": str})
    cand = d[d["备注"].isin(["晋级", "观察"])].copy()
    ind = load_industry(cand["code"].tolist())
    cand["行业"] = cand["code"].map(lambda c: ind.get(c, "未知"))
    cand["画像判定"] = cand["行业"].map(judge)
    order = ["画像判定", "备注", "mktcap亿", "净利同比%"]
    cand["_o"] = cand["画像判定"].str.startswith("保留") * -1
    cand = cand.sort_values(order, ascending=[True, True, False, False]).drop(columns="_o")
    cand.to_csv(OUT, index=False, encoding="utf-8-sig")
    n_keep = cand["画像判定"].str.startswith("保留").sum()
    print(f"# 候选 {len(cand)} 只(晋级{sum(cand['备注']=='晋级')}+观察{sum(cand['备注']=='观察')}) "
          f"-> 画像保留 {n_keep} / 剔除 {len(cand)-n_keep};输出 {OUT}")
    print(cand[cand["画像判定"].str.startswith("保留")][
        ["code", "name", "备注", "行业", "画像判定", "mktcap亿", "净利同比%"]].to_string(index=False))

# 超哥选股 (chaogexuangu)

Serenity 瓶颈投资法 A 股全市场选股工具链:从全 A 股 5000+ 只,用四步漏斗筛到个位数的候选标的,每一步都有可追溯的数据和明确的淘汰规则。

> 以上市公司公开数据为原料(akshare/东财/腾讯免费接口),不依赖任何付费数据源;全部结论可复现、可证伪。

## 方法论:Serenity 四步漏斗

1. **逆向拆解瓶颈**:从赛道出发拆 BOM,六问筛真瓶颈(物理必需/扩产≥18个月/供应商≤3家/BOM占比≤5%/缺失即停产/低关注度)
2. **穿透财务拐点**:毛利率连续 2 季环比升、CapEx 连续增、OCF/净利≥0.8、合同负债连续升——≥3 项通过才放行,且必须用最新季报净利同比二次确认
3. **锁定非对称标的**:市值 30-150 亿、机构评级 ≤10 家、日均成交额 ≥5000 万、细分市占率前三、机构持仓低
4. **AI 红队证伪**:扮演空头,技术替代/大客户自研/供应链断裂三维度证伪,高风险≥2 直接否决

配套**熔断机制**:每个入选标的设定 3-5 个 6 个月内可验证的里程碑,未达成即清仓。

完整规则见 [serenity-analyst.md](serenity-analyst.md)(含标准作业程序 SOP 和实战中踩出的 7 条坑清单)。

## 快速开始(网页版,推荐)

```bash
pip install -r requirements.txt   # Python 3.10+;只依赖 akshare + pandas,免费公开接口
python selftest.py                # 先自检(不联网),4/4 OK 再往下
python app.py                     # 起本地网页 http://127.0.0.1:8000
```

打开网页点"一键获取今日候选":数据新鲜(当天跑过)秒出全表;过期自动跑完整流水线(约 4 分钟,页面实时显示进度日志)。支持关键字过滤、红队评级高亮。仅监听本机 127.0.0.1。

## 快速开始(命令行版)

```bash
pip install -r requirements.txt
python selftest.py                # 先自检(不联网),4/4 OK 再往下
python run_all.py 30 150 1.0      # 一键机器段:粗筛→财务初筛→画像预筛,约 4 分钟
```

机器段产物链:`candidates.csv`(市值/流动性粗筛)→ `full_screen_results.csv`(财务判定,**晋级**+**观察**+伪拐点拦截,含净利同比列)→ `pool_candidates.csv`(贴 EM2016 行业+关键词画像剔除,按保留优先排序)。

也可分步执行与调参:

```bash
python screen.py 30 150 1.0       # 分步①:粗筛,可自定义市值/换手阈值
python batch_check2.py            # 分步②:报告期自动推导(按披露截止取最近5期),无需手改
python build_pool.py              # 分步③:画像预筛(EM2016 行业 + 11 组剔除关键词)
python check.py 301568            # 单只精确终审:真实在建工程/合同负债/单季三表,JSON 输出
python industry_map.py codes.txt  # 任意代码清单的行业映射(新浪+F10 组合)
```

人工/LLM 段(机器替代不了的部分):

1. **画像终审**:从 `pool_candidates.csv` 保留区里按产业常识定夺(关键词有漏网/误伤,以人判为准)
2. **精确终审**:对入选者逐只 `python check.py <代码>`,两引擎一致才晋级,冲突降"待定"
3. **红队证伪**:每只一搜(最新季报实绩+风险公告),三维度证伪,高风险≥2 否决;扣非与归母增速背离是伪拐点重灾区
4. **熔断里程碑**:通过者按模板定 3-5 个 6 个月里程碑(见 serenity-screen-result.md 示例)

全流程规则与实战坑见 [serenity-analyst.md](serenity-analyst.md);历次筛选结果存档见 [serenity-screen-result.md](serenity-screen-result.md)。

## 一次完整实盘的结果(2026-09)

全流程实跑记录见 [serenity-screen-result.md](serenity-screen-result.md):

```
全 A 5222 → 硬标准 2355 → 财务拐点 29 → 画像 9 → 红队证伪 → 通过 1 + 待定 4 + 否决 4
```

数据快照:`candidates.csv`(粗筛池)、`full_screen_results.csv`(全市场判定明细)、`final_pool.csv`(终审池)。

## 实战验证出的关键教训

- **伪拐点**:毛利率环比升是弱信号,9 只过四项判定的标的里 4 只中报净利暴跌 60%~96%——必须做净利同比二次确认
- **代理口径必有假阳性**:批量表的"营业总支出/投资现金流"与真实"营业成本/购建 CapEx"方向可能相反,初筛≠终审
- **净利为负时 OCF/净利比值无意义**(负负得正),已做守卫
- 东财 push2 行情域不稳定 → 行情走腾讯源;报表接口必须重试 + 字段名兜底(版本漂移)
- 逐股拉报表 60s/只不可行,必须按报告期批量接口(39h → 3min)

## 可选:接 TradingAgents-CN 多智能体辩论层

将候选池丢进 [TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN)(自托管,DeepSeek/Qwen 等)做交叉验证;`nginx.conf` 是其前端反代 `/api` 到后端的修正配置(官方镜像默认指向 localhost,远程访问会 405)。

## 免责声明

本项目仅为研究工具与方法论实践,**不构成任何投资建议**。数据来自公开免费接口,不保证准确性;入市有风险,决策需独立。

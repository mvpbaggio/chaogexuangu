# AI 选股项目(Serenity 瓶颈投资法)

## 架构与分工

| 层 | 位置 | 内容 |
|---|---|---|
| 数据层 | **Windows 本机** | `check.py`(akshare:财报三大表/研报 + 腾讯行情),输出量化 JSON |
| 分析层 | **ZCode 内** | `serenity-analyst.md` 角色提示词:四步漏斗筛选 + 红队证伪 + 熔断机制 |
| 辩论层(可选) | **NAS Docker** | TradingAgents-CN 多智能体 Web(`http://NAS_IP:3000` 前端 / `:8000` API) |

工作流:指定赛道 → 拆 BOM 找瓶颈(第一步,LLM)→ `check.py` 财务验证(第二步)→ 硬性筛选(第三步)→ 红队证伪(第四步)→ 输出综合评级 + 熔断里程碑。

## 使用

### 数据层(本机)
```bash
PY=F:/工具箱/AI工具/.zcode/tools/python312/python.exe
$PY F:/工具箱/AI工具/.zcode/tools/ai-stock-picking/check.py 600519          # 单只
$PY check.py 600519 --hist                                                  # 附带近60日行情
```
输出 JSON 含:近4季度单季毛利率/CapEx/在建工程同比/OCF比净利润/合同负债 + 市值/日均成交额/研报篇数,并自动给出第二步四项验证判定。

### 分析层
把 `serenity-analyst.md` 作为角色提示词,配合 `check.py` 输出执行四步流程。所有数字必须来自脚本或标注来源,无来源标"待核实"。

### 辩论层(NAS)
已部署完成:backend/frontend/mongodb/redis 四容器常驻,后端 `/api/health` 健康。
**首次使用前必须**:`ssh nas` 编辑 `/data_VRJV6L7K/data/udata/real/ai-stock-picking/TradingAgents-CN/.env`,填 `DEEPSEEK_API_KEY=... DEEPSEEK_ENABLED=true`(或其它供应商 key),然后 `../bin/docker-compose up -d` 重启。
访问 `http://192.168.0.114:3000`(前端)/ `:8000`(API)。

## 数据源说明
- **东财 push2 行情接口不稳定**(曾整域不通),行情一律走腾讯源 `stock_zh_a_hist_tx`;财报接口走东财。
- 市值 = 最新收盘价 × 总股本(资产负债表 SHARE_CAPITAL),非东财实时市值,盘后口径。
- 单季 CapEx 为相邻报告期累计值差分,可为负(退款/冲回),分析时注意。
- 研报接口返回**篇数**非评级家数,精确"买入/增持家数 ≤10"需人工或后续用 easy_tdx/其他接口核实。
- easy_tdx(`pip install easy-tdx`)留作分钟线/实时盘口/行情备份,首版未接。

## 已知边界(ponytail)
- 东财报表字段名随版本变动,在建工程(CIP)缺失时该项标"待核实"不阻塞。
- 第三步标准④(市占率)与⑤(前十大流通股东机构占比)无免费稳定接口,由分析环节引用公开资料,无来源标"待核实"。

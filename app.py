# -*- coding: utf-8 -*-
"""Serenity 选股本地网页:按日期查看/重算符合画像的候选股票。
- 跑过的日期自动存档到 results/YYYY-MM-DD/,选中秒回放;
- 无存档的日期可"重算":财报按该日期披露口径,行情快照为最新(页面明示口径差异)。
仅用标准库。用法:python app.py  浏览器开 http://127.0.0.1:8001
"""
import json, os, shutil, subprocess, sys, threading, time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
ARCHIVE = os.path.join(ROOT, "results")
PORT = int(os.environ.get("PORT", "8001"))

RUN = {"state": "idle", "lines": [], "started": 0.0, "ended": 0.0, "date": ""}
LOCK = threading.Lock()


def files_for(d: str):
    """某日期的产物文件目录:今天用工作区实时文件;其余日期必须有存档,没有就报无存档。"""
    if d == date.today().isoformat():
        return ROOT, os.path.exists(os.path.join(ROOT, "pool_candidates.csv"))
    dst = os.path.join(ARCHIVE, d)
    return dst, os.path.isdir(dst) and os.path.exists(os.path.join(dst, "pool_candidates.csv"))


def archived_dates():
    if not os.path.isdir(ARCHIVE):
        return []
    out = []
    for n in os.listdir(ARCHIVE):
        if len(n) == 10 and os.path.exists(os.path.join(ARCHIVE, n, "pool_candidates.csv")):
            out.append(n)
    return sorted(out, reverse=True)


def run_pipeline(asof: str):
    """后台跑 run_all.py(可选 as-of 日期),产物存档到 results/<asof>。"""
    def work():
        env = dict(os.environ, SERENITY_ASOF=asof)
        p = subprocess.Popen([sys.executable, "run_all.py", "30", "150", "1.0"],
                             cwd=ROOT, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace", bufsize=1)
        for line in p.stdout:
            RUN["lines"].append(line.rstrip())
        code = p.wait()
        RUN["ended"] = time.time()
        if code == 0 and asof != date.today().isoformat():
            dst = os.path.join(ARCHIVE, asof)
            os.makedirs(dst, exist_ok=True)
            for f in ("candidates.csv", "full_screen_results.csv", "pool_candidates.csv"):
                if os.path.exists(os.path.join(ROOT, f)):
                    shutil.copy2(os.path.join(ROOT, f), dst)
            RUN["lines"].append(f"# 已存档到 results/{asof}/")
        RUN["state"] = "done" if code == 0 else "fail"

    with LOCK:
        if RUN["state"] == "running":
            return
        RUN.update(state="running", lines=[], started=time.time(), ended=0.0, date=asof)
    threading.Thread(target=work, daemon=True).start()


def load_results(d: str):
    """合并产物为一个数据包:漏斗计数 + 终审通过卡片 + 候选表。"""
    base, _ = files_for(d)
    fun = {"scanned": 0, "promoted": 0, "watch": 0, "pseudo": 0, "keep": 0, "excluded": 0, "passed": 0}
    fs = pd.read_csv(os.path.join(base, "full_screen_results.csv"), dtype={"code": str})
    fun["scanned"] = len(pd.read_csv(os.path.join(base, "candidates.csv"), dtype={"code": str}))
    vc = fs["备注"].value_counts().to_dict()
    fun["promoted"] = vc.get("晋级", 0)
    fun["watch"] = vc.get("观察", 0)
    fun["pseudo"] = sum(v for k, v in vc.items() if k.startswith("伪拐点"))
    pool = pd.read_csv(os.path.join(base, "pool_candidates.csv"), dtype={"code": str})
    pool["保留"] = pool["画像判定"].str.startswith("保留")
    fun["keep"] = int(pool["保留"].sum())
    fun["excluded"] = int((~pool["保留"]).sum())
    fp = os.path.join(ROOT, "final_pool.csv")  # 红队评级来自最近一次人工终审存档
    if os.path.exists(fp):
        red = pd.read_csv(fp, dtype={"code": str}).set_index("code")
        for col in ("红队评级", "精确判定", "红队要点"):
            if col in red.columns:
                pool[col] = pool["code"].map(red[col])
        passed = red[red.get("红队评级", pd.Series(dtype=str)).fillna("").str.startswith("通过")]
        fun["passed"] = len(passed)
        passed = passed.reset_index().to_dict("records")
    else:
        passed = []
    keep = pool[pool["保留"]].sort_values("mktcap亿", ascending=False).drop(columns="保留")
    excl = pool[~pool["保留"]].sort_values("mktcap亿", ascending=False).drop(columns="保留")
    j = lambda df: json.loads(df.to_json(orient="records", force_ascii=False))
    return {"funnel": fun, "passed": passed, "keep": j(keep), "excluded": j(excl)}


PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>Serenity 选股</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}body{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:0;background:#f4f6f8;color:#1a1a1a}
header{background:#0d2b45;color:#fff;padding:14px 24px;display:flex;flex-wrap:wrap;gap:12px;align-items:center}
header h1{font-size:18px;margin:0;flex:1}
header select,header input,header button{font-size:14px;padding:7px 10px;border:0;border-radius:6px}
header button{background:#12a76f;color:#fff;cursor:pointer}header button.orange{background:#e67e22}
header button:disabled{opacity:.5;cursor:wait}
main{max-width:1100px;margin:0 auto;padding:18px 20px}
.funnel{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:6px 0 18px}
.funnel .st{background:#fff;border:1px solid #dde3e8;border-radius:8px;padding:8px 14px;text-align:center}
.funnel .st b{display:block;font-size:20px;color:#0d2b45}.funnel .st span{font-size:12px;color:#667}
.funnel .arr{color:#98a3ad;font-size:18px}
h2{font-size:15px;color:#445;margin:18px 0 8px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px}
.card{background:#fff;border:1px solid #dde3e8;border-left:4px solid #12a76f;border-radius:8px;padding:10px 12px}
.card b{font-size:15px}.card .code{color:#888;font-size:12px}
.card .ind{font-size:12px;color:#445;margin:4px 0}
.card .pts{font-size:12px;color:#667;margin-top:4px}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:10px;background:#e6f6ef;color:#0a7d54;margin-top:5px}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
.bar input[type=text]{flex:1;min-width:160px;padding:7px 10px;border:1px solid #ccd3da;border-radius:6px}
#stat{font-size:13px;color:#667}
#log{background:#101418;color:#cde3d8;padding:10px;height:160px;overflow:auto;font:12px/1.5 Consolas,monospace;white-space:pre-wrap;border-radius:8px;display:none;margin-bottom:10px}
table{border-collapse:collapse;width:100%;background:#fff;font-size:13px;border-radius:8px;overflow:hidden}
th,td{border-bottom:1px solid #edf0f2;padding:7px 10px;text-align:left;white-space:nowrap}
th{background:#eef1f4;font-weight:600;position:sticky;top:0}
tr:hover td{background:#f7fafc}
.pill{font-size:11px;padding:2px 8px;border-radius:10px}
.pill.j{background:#e6f6ef;color:#0a7d54}.pill.o{background:#fdf3e4;color:#b06f13}.pill.r{background:#fde8e8;color:#c0392b}
label{font-size:13px;color:#555}
footer{color:#8b959e;font-size:12px;padding:14px 20px;text-align:center}
</style></head><body>
<header>
  <h1>Serenity 瓶颈投资法 · 候选筛选</h1>
  <input type="date" id="date">
  <select id="dates"><option value="">选择存档日期…</option></select>
  <button id="go">查询</button>
  <button id="force" class="orange">按此日期重算</button>
</header>
<main>
  <div class="funnel" id="funnel"></div>
  <div class="bar">
    <input type="text" id="q" placeholder="过滤:代码 / 名称 / 行业 / 评级…">
    <label><input type="checkbox" id="all"> 显示已剔除</label>
    <span id="stat"></span>
  </div>
  <div id="log"></div>
  <h2>今日终审通过 <span id="nPassed" style="color:#888;font-weight:400"></span></h2>
  <div class="cards" id="passed"></div>
  <h2>候选池 <span id="nCand" style="color:#888;font-weight:400"></span></h2>
  <div id="tbl"></div>
  <p style="color:#8b959e;font-size:12px" id="warn"></p>
</main>
<footer>机器预筛 + 人工红队终审;财报判定按所选日期披露口径,重算日期的行情快照为最新值。研究用途,不构成投资建议。<b>BUILD __BUILD__</b></footer>
<script>
const $=s=>document.querySelector(s);const esc=v=>v==null?'':String(v);
let DATA=null,DATE='',TIMER=null;
const today=new Date().toISOString().slice(0,10);
$('#date').value=today;

function funnel(f){
  if(!f)return '';
  const st=(n,l)=>'<div class="st"><b>'+n+'</b><span>'+l+'</span></div>';
  const a='<div class="arr">→</div>';
  return st(f.scanned,'粗筛后')+a+st(f.promoted,'财务晋级')+st(f.watch,'观察档')+
    (f.pseudo?a+st(f.pseudo,'伪拐点拦截'):'')+a+st(f.keep,'画像保留')+
    a+st(f.passed,'终审通过');
}
function pill(k){
  if(k=='晋级')return '<span class="pill j">晋级</span>';
  if(k=='观察')return '<span class="pill o">观察</span>';
  if((k||'').startsWith('伪拐点'))return '<span class="pill r">伪拐点</span>';
  return '<span class="pill">'+esc(k)+'</span>';
}
function renderPassed(ps){
  $('#nPassed').textContent=ps.length?('('+ps.length+' 只)'):'(终审存档中暂无)';
  $('#passed').innerHTML=ps.map(p=>{
    const ok=(p['红队评级']||'').startsWith('通过');
    return '<div class="card" style="border-left-color:'+(ok?'#12a76f':'#e67e22')+'">'+
      '<b>'+esc(p['name'])+'</b> <span class="code">'+esc(p['code'])+'</span><br>'+
      '<div class="ind">'+esc(p['画像'])+'</div>'+
      '<div class="pts">'+esc(p['红队要点'])+'</div>'+
      '<div>净利同比 '+(p['净利同比%']!=null?(+p['净利同比%']).toFixed(1)+'%':'-')+
      ' · 精确 '+esc(p['精确判定'])+'</div>'+
      '<span class="tag">'+esc(p['红队评级'])+'</span></div>'}).join('')||'<p style="color:#8b959e">尚无终审通过记录</p>';
}
function renderTable(){
  if(!DATA)return;
  const q=$('#q').value.trim(),showAll=$('#all').checked;
  const rows=DATA.keep.concat(DATA.excluded).filter(r=>
    (showAll||!DATA.excluded.includes(r))&&(!q||Object.values(r).some(v=>esc(v).includes(q))));
  const cols=['code','name','备注','行业','mktcap亿','净利同比%','红队评级'];
  $('#tbl').innerHTML='<table><tr>'+cols.map(c=>'<th>'+({'code':'代码','name':'名称','备注':'档位','行业':'行业','mktcap亿':'市值(亿)','净利同比%':'净利同比','红队评级':'红队'}[c]||c)+'</th>').join('')+'</tr>'+
    rows.map(r=>'<tr>'+cols.map(c=>{
      let v=esc(r[c]);
      if(c=='备注')v=pill(r['备注']);
      if(c=='净利同比%'&&r[c]!=null)v=(+r[c]).toFixed(1)+'%';
      if(c=='红队评级'&&v)v='<span class="'+(v.startsWith('通过')?'pill j':'pill r')+'">'+v+'</span>';
      return '<td>'+v+'</td>';}).join('')+'</tr>').join('')+'</table>';
  $('#nCand').textContent='('+rows.length+' 只,候选池存档共 '+(DATA.keep.length+DATA.excluded.length)+' 只)';
}
async function load(d){
  const r=await(await fetch('/api/data?date='+d)).json();
  DATA=r;DATE=d;
  $('#funnel').innerHTML=funnel(r.funnel);
  renderPassed(r.passed||[]);
  $('#all').checked=false;renderTable();
  $('#warn').textContent=r.warn||'';
}
async function poll(){
  const r=await(await fetch('/api/status')).json();
  let stat='';
  if(r.state=='running')stat='重算中('+esc(r.date)+') '+((Date.now()/1000-r.started)|0)+'s…';
  else if(r.state=='done'&&r.ended)stat='上次重算 '+esc(r.date)+' 完成,耗时 '+(((r.ended-r.started)/60)|0)+'分'+((((r.ended-r.started)/60)%1)*60|0)+'秒';
  else if(r.state=='fail')stat='失败,见日志';
  $('#stat').textContent=stat;
  if(r.state!='idle'){const log=$('#log');log.style.display='block';log.textContent=r.lines.join('\\n');log.scrollTop=1e9}
  if(r.state=='running')return;
  clearInterval(TIMER);TIMER=null;$('#go').disabled=false;$('#force').disabled=false;
  if(r.state=='done')await load($('#date').value);
}
async function loadDates(){
  const ds=await(await fetch('/api/dates')).json();
  $('#dates').innerHTML='<option value="">选择存档日期…</option>'+
    ds.map(d=>'<option>'+d+'</option>').join('');
}
$('#q').oninput=renderTable;$('#all').onchange=renderTable;
$('#dates').onchange=e=>{$('#date').value=e.target.value;load(e.target.value)};
$('#go').onclick=()=>{clearInterval(TIMER);load($('#date').value)};
async function runIt(){const d=$('#date').value;
  if(!d)return alert('先选日期');
  $('#go').disabled=true;$('#force').disabled=true;
  await fetch('/api/run?date='+d);
  TIMER=setInterval(poll,1500);poll()}
$('#force').onclick=runIt;
loadDates();load(today);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body if isinstance(body, bytes) else body.encode("utf-8"))

    def do_GET(self):
        p = urlparse(self.path)
        q = parse_qs(p.query)
        if p.path == "/":
            self._send(200, self._page, "text/html; charset=utf-8")
        elif p.path == "/api/dates":
            self._send(200, json.dumps(archived_dates(), ensure_ascii=False),
                       "application/json; charset=utf-8")
        elif p.path == "/api/data":
            d = (q.get("date") or [date.today().isoformat()])[0]
            base, exists = files_for(d)
            if not exists:
                self._send(200, json.dumps({"warn": f"{d} 无存档:点「按此日期重算」生成", "funnel": None,
                                            "passed": [], "keep": [], "excluded": []},
                                           ensure_ascii=False), "application/json; charset=utf-8")
                return
            data = load_results(d)
            if d != date.today().isoformat() and base != ROOT:
                data["warn"] = f"{d} 为历史存档回放;若为「按日期重算」产物,财报口径为当日,行情快照为最新值"
            self._send(200, json.dumps(data, ensure_ascii=False), "application/json; charset=utf-8")
        elif p.path == "/api/status":
            self._send(200, json.dumps(RUN, ensure_ascii=False), "application/json; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        p = urlparse(self.path)
        if p.path == "/api/run":
            d = (parse_qs(p.query).get("date") or [date.today().isoformat()])[0]
            base, exists = files_for(d)
            if not exists or d == date.today().isoformat():
                run_pipeline(d)
            self._send(200, json.dumps({"ok": True, "date": d}, ensure_ascii=False),
                       "application/json; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain")


if __name__ == "__main__":
    H._page = PAGE.replace("__BUILD__", time.strftime("%Y-%m-%d %H:%M"))
    print(f"Serenity 选股网页: http://127.0.0.1:{PORT}  (Ctrl+C 退出)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()

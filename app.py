# -*- coding: utf-8 -*-
"""Serenity 选股本地网页:一键取得今天符合画像的候选股票。
仅用标准库。数据新鲜(当日已跑过流水线)则秒出;过期则自动跑 screen→batch→build_pool。
用法:python app.py  然后浏览器开 http://127.0.0.1:8000
"""
import json, os, subprocess, sys, threading, time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
FRESH_FILE = os.path.join(ROOT, "pool_candidates.csv")   # 流水线末段产物,新鲜度以此为准
PORT = int(os.environ.get("PORT", "8000"))

# 全局运行态(单机单用户工具,一把锁够用)
RUN = {"state": "idle", "lines": [], "started": 0.0, "ended": 0.0}  # idle|running|done|fail
LOCK = threading.Lock()


def is_fresh() -> bool:
    return os.path.exists(FRESH_FILE) and date.fromtimestamp(os.path.getmtime(FRESH_FILE)) == date.today()


def run_pipeline():
    """后台跑 run_all.py,输出行进缓冲到 RUN。"""
    def work():
        p = subprocess.Popen([sys.executable, "run_all.py", "30", "150", "1.0"],
                             cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", bufsize=1)
        for line in p.stdout:
            RUN["lines"].append(line.rstrip())
        code = p.wait()
        RUN["ended"] = time.time()
        RUN["state"] = "done" if code == 0 else "fail"
    with LOCK:
        if RUN["state"] == "running":
            return
        RUN.update(state="running", lines=[], started=time.time())
    threading.Thread(target=work, daemon=True).start()


def load_results():
    """pool_candidates(画像判定) + final_pool(红队评级,若有) 合并出表。"""
    df = pd.read_csv(FRESH_FILE, dtype={"code": str})
    fp = os.path.join(ROOT, "final_pool.csv")
    if os.path.exists(fp):
        red = pd.read_csv(fp, dtype={"code": str}).set_index("code")
        if "红队评级" in red.columns:
            df["红队评级"] = df["code"].map(red["红队评级"])
    df["保留"] = df["画像判定"].str.startswith("保留")
    cols = ["code", "name", "备注", "行业", "画像判定", "红队评级", "mktcap亿", "净利同比%",
            "①毛利率升", "②CapEx增(参考不计分)", "③OCF/净利", "④预收增(代理)"]
    cols = [c for c in cols if c in df.columns]
    df["_o"] = (~df["保留"]).astype(int)
    df = df.sort_values(["_o", "mktcap亿"], ascending=[True, False]).drop(columns="_o")
    return json.loads(df[cols].to_json(orient="records", force_ascii=False))


PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>Serenity 今日候选</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:24px;background:#111;color:#ddd}
h1{font-size:20px} #bar{margin:12px 0}
button{padding:10px 22px;font-size:16px;background:#0a7;border:0;border-radius:6px;color:#fff;cursor:pointer}
button:disabled{background:#555;cursor:wait}
#log{background:#000;padding:10px;height:180px;overflow:auto;font:12px/1.5 Consolas,monospace;white-space:pre-wrap;display:none}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:12px}
th,td{border:1px solid #333;padding:5px 8px;text-align:left;white-space:nowrap}
th{background:#1c1c1c;position:sticky;top:0}
tr.keep td:first-child{border-left:3px solid #0a7}
.bad{color:#c33}.ok{color:#2c6}
input{padding:6px;font-size:14px;background:#1c1c1c;color:#ddd;border:1px solid #333;border-radius:4px}
.tag{font-size:11px;padding:1px 6px;border-radius:3px;background:#333}
</style></head><body>
<h1>Serenity 瓶颈投资法 · 今日候选 <span id="fresh" class="tag"></span></h1>
<div id="bar"><button id="go">一键获取今日候选</button>
<button id="force" style="background:#e80">强制重跑全流程</button>
<input id="q" placeholder="过滤:代码/名称/行业/评级…">
<label style="font-size:13px"><input type="checkbox" id="all"> 显示已剔除</label>
<span id="stat"></span></div>
<div id="log"></div>
<div id="tbl"></div>
<p style="color:#777;font-size:12px">机器预筛结果(画像保留区排前),红队评级来自人工终审存档;研究用途,不构成投资建议。<b>BUILD __BUILD__</b></p>
<script>
let DATA=[],TIMER=null;
const $=s=>document.querySelector(s);
function esc(v){return v==null?'':String(v)}
function render(){
  const q=$('#q').value.trim();
  const showAll=$('#all').checked;
  const rows=DATA.filter(r=>(showAll||((r['画像判定']||'').startsWith('保留')))
                      &&(!q||Object.values(r).some(v=>esc(v).includes(q))));
  const cols=DATA.length?Object.keys(DATA[0]):[];
  $('#tbl').innerHTML='<table><tr>'+cols.map(c=>'<th>'+c+'</th>').join('')+'</tr>'+
    rows.map(r=>{
      const keep=(r['画像判定']||'').startsWith('保留');
      const cells=cols.map(c=>{
        let v=esc(r[c]);
        if(c=='红队评级'&&v)v='<span class="'+(v.startsWith('通过')?'ok':'bad')+'">'+v+'</span>';
        return '<td>'+v+'</td>';}).join('');
      return '<tr class="'+(keep?'keep':'')+'">'+cells+'</tr>';}).join('')+
    '</table><p>'+rows.length+' / '+DATA.length+' 只</p>';
}
async function poll(){const r=await (await fetch('/api/status')).json();
  let stat='';
  if(r.state=='running')stat='运行中 '+((Date.now()/1000-r.started)|0)+'s';
  else if(r.state=='done'&&r.ended)stat='上次跑完 '+new Date(r.ended*1000).toLocaleTimeString()+
    ',耗时 '+(((r.ended-r.started)/60)|0)+'分'+((((r.ended-r.started)/60)%1)*60|0)+'秒';
  else if(r.state=='fail')stat='失败,见日志';
  $('#stat').textContent=stat;
  if(r.state!='idle'){const log=$('#log');log.style.display='block';log.textContent=r.lines.join('\\n');log.scrollTop=1e9}
  if(r.state=='running')return;
  clearInterval(TIMER);TIMER=null;
  if(r.state=='done'||r.fresh){await load();$('#go').disabled=false;$('#force').disabled=false}
  if(r.state=='fail')$('#stat').textContent='失败,见日志';
}
async function load(){const r=await (await fetch('/api/data')).json();
  DATA=r.rows;$('#fresh').textContent=r.fresh?('数据日期:今天'):('数据过期:'+r.date);
  render();$('#tbl').style.display=''}
$('#q').oninput=render;$('#all').onchange=render;
async function runIt(force){[ $('#go'),$('#force') ].forEach(b=>b.disabled=true);
  await fetch('/api/run'+(force?'?force=1':''));
  TIMER=setInterval(poll,1500);poll()}
$('#go').onclick=()=>runIt(false);
$('#force').onclick=()=>runIt(true);
load();
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 静默访问日志
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")  # 页面/接口都禁缓存,改版即生效
        self.end_headers()
        self.wfile.write(body if isinstance(body, bytes) else body.encode("utf-8"))

    def do_GET(self):
        p = urlparse(self.path)
        if p.path == "/":
            self._send(200, self._page, "text/html; charset=utf-8")
        elif p.path == "/api/data":
            fresh = is_fresh()
            rows = load_results() if fresh else []
            self._send(200, json.dumps({"fresh": fresh, "date": date.fromtimestamp(
                os.path.getmtime(FRESH_FILE)).isoformat() if os.path.exists(FRESH_FILE) else "无",
                "rows": rows}, ensure_ascii=False), "application/json; charset=utf-8")
        elif p.path == "/api/status":
            self._send(200, json.dumps({**RUN, "fresh": is_fresh()}, ensure_ascii=False),
                       "application/json; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        p = urlparse(self.path)
        if p.path == "/api/run":
            force = "force=1" in (p.query or "")
            if force or not is_fresh():
                run_pipeline()
            self._send(200, json.dumps({"ok": True, "force": force}, ensure_ascii=False),
                       "application/json; charset=utf-8")
        else:
            self._send(404, "not found", "text/plain")


if __name__ == "__main__":
    PAGE_S = PAGE.replace("__BUILD__", time.strftime("%Y-%m-%d %H:%M"))
    print(f"Serenity 选股网页: http://127.0.0.1:{PORT}  (Ctrl+C 退出)", flush=True)
    TH = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    H._page = PAGE_S  # 当前构建版页面(带 BUILD 戳)
    TH.serve_forever()

# -*- coding: utf-8 -*-
"""一键全流程:粗筛 -> 财务初筛 -> 画像预筛。耗电商约 4 分钟(依赖东财/新浪接口)。
用法:python run_all.py [最小市值亿] [最大市值亿] [最小换手%]
产物:candidates.csv -> full_screen_results.csv -> pool_candidates.csv(人工/LLM 终审)
"""
import subprocess, sys, os

PY = sys.executable
STEPS = [("screen.py", True), ("batch_check2.py", False), ("build_pool.py", False)]

for script, has_args in STEPS:
    cmd = [PY, script] + (sys.argv[1:] if has_args else [])
    print(f"\n===== {script} =====", flush=True)
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit(f"{script} 失败,流程中止")
print("\n全流程完成。pool_candidates.csv 为机器预筛,终审(精确 check.py + 红队)见 serenity-analyst.md SOP。")

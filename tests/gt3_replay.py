"""Replay the production GT3 solve path with FULL log retention + timing.

Reads: bilibili captcha init (GET), geetest assets. Submits an answer to
geetest's ajax.php only (no bilibili account involved).
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from biliwb import gt3

OUT = pathlib.Path(__file__).resolve().parent / "_gt3_run"
OUT.mkdir(exist_ok=True)

d = gt3.DEFAULT_SOLVER_DIR
cmd = [
    sys.executable, str(d / "gt3_protocol.py"),
    "--source", "main-fe",
    "--max-http", "20",
    "--patched-core", "--patched-click",
    "--call-widget", "$_BJJQ",
    "--answer-format", "pct",
    "--verify-first",
    "--timer-cap", "2000",
    "--helper-rounds", "80",
]
print("CMD:", " ".join(cmd), flush=True)
t0 = time.time()
proc = subprocess.run(cmd, cwd=str(d), capture_output=True, text=True, timeout=900)
el = time.time() - t0
log = (proc.stdout or "") + "\n=== STDERR ===\n" + (proc.stderr or "")
(OUT / "full.log").write_text(log, encoding="utf-8", errors="replace")
print(f"rc={proc.returncode} elapsed={el:.1f}s log_bytes={len(log)}", flush=True)

print("--- round line ---")
for m in re.finditer(r"\[round\].*", log):
    print(m.group(0))
print("--- verdicts ---")
for m in re.finditer(r"\[verdict\].*", log):
    print(m.group(0)[:300])
print("--- SUCCESS ---")
for m in re.finditer(r"=== SUCCESS.*", log):
    print(m.group(0))
print("--- solve summaries ---")
for m in re.finditer(r"\[solve\] .*", log):
    print(m.group(0)[:500])
print("--- http lines (last 25) ---")
lines = [ln for ln in log.splitlines() if "[http" in ln or "[helper:req" in ln or "[helper]" in ln]
for ln in lines[-25:]:
    print(ln)
print("--- warnings/errors ---")
for ln in log.splitlines():
    if "warn" in ln or "error" in ln.lower() or "=== w values" in ln:
        print(ln[:300])
res = gt3.solve_once.__doc__ and None
# also show what the production wrapper would parse
ROUND_RE, SUCCESS_RE, VERDICT_RE = gt3.ROUND_RE, gt3.SUCCESS_RE, gt3.VERDICT_RE
rounds = ROUND_RE.findall(log)
print("parsed rounds:", rounds)
print("parsed success:", SUCCESS_RE.search(log).groups() if SUCCESS_RE.search(log) else None)
print("parsed verdicts:", VERDICT_RE.findall(log))

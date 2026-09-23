"""Browser-free GT3 (bilibili word-click) solver -- single entry point.

    python main.py                 # two fresh rounds, prints the validate codes
    python main.py --rounds 3

What runs, with no browser/CDP/Playwright/Selenium anywhere in the path:

  1. a fresh gt/challenge is taken from passport.bilibili.com (x/passport-login/captcha)
  2. `env/run.js` (node:vm + the env-patch profile) executes the raw geetest assets --
     fullpage.9.2.0-guwyxh.js and click.3.1.2.js -- and Python answers every HTTP request
     they make (gettype.php, get.php, ajax.php, gct, styles, the round JPEG)
  3. the round JPEG is solved locally: the prompt card (bottom-left 116x40 of the round
     image, exactly what .geetest_tip_img shows) gives the click count and the characters;
     every field glyph is re-OCR'd over a full rotation sweep with two ddddocr models and
     matched to the prompt characters (see gt3_click_solve_v11.py)
  4. the widget's own submission method ($_BJJQ) builds the final `w`
     (AES + RSA + custom base64) and the helper posts it to /ajax.php
  5. the server's verdict is reported: {"result":"success","validate":...}

Exit status is 0 only if every requested round returned a validate code.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import time

TASK = pathlib.Path(__file__).resolve().parent
SUCCESS_RE = re.compile(r"=== SUCCESS validate=(\S+) score=(\S+) ===")


def run_round(round_no: int, max_http: int, timeout: int) -> dict:
    cmd = [
        sys.executable, str(TASK / "gt3_protocol.py"),
        "--max-http", str(max_http),
        "--patched-core", "--patched-click",
        "--call-widget", "$_BJJQ",
        "--answer-format", "pct",
        "--verify-first",
        "--timer-cap", "2000",
        "--helper-rounds", "80",
    ]
    started = time.time()
    proc = subprocess.run(cmd, cwd=str(TASK), capture_output=True, text=True, timeout=timeout)
    out = (proc.stdout or "") + (proc.stderr or "")
    m = SUCCESS_RE.search(out)
    verdicts = re.findall(r"\[verdict\].*?-> (\{.*?\})\s*$", out, re.M)
    used = re.search(r"http used: (\d+)", out)
    res = {
        "round": round_no,
        "ok": bool(m),
        "validate": m.group(1) if m else None,
        "score": m.group(2) if m else None,
        "verdict": json.loads(verdicts[-1]) if verdicts else None,
        "http_used": int(used.group(1)) if used else None,
        "seconds": round(time.time() - started, 1),
    }
    if not res["ok"]:
        tail = [ln for ln in out.splitlines() if "[verdict]" in ln or "SUCCESS" in ln][-3:]
        res["tail"] = tail
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=2, help="fresh challenges to solve (2-3 recommended)")
    ap.add_argument("--max-http", type=int, default=20, help="per-round HTTP budget for the SDK's own requests")
    ap.add_argument("--timeout", type=int, default=900, help="seconds per round")
    args = ap.parse_args()

    print(f"browser-free GT3 solve: {args.rounds} fresh round(s) from passport.bilibili.com")
    results = []
    for i in range(1, args.rounds + 1):
        res = run_round(i, args.max_http, args.timeout)
        results.append(res)
        if res["ok"]:
            print(f"  round {i}: SUCCESS validate={res['validate']} score={res['score']} "
                  f"http={res['http_used']} {res['seconds']}s")
        else:
            print(f"  round {i}: FAIL verdict={res['verdict']} http={res['http_used']} {res['seconds']}s")
            for ln in res.get("tail") or []:
                print(f"      {ln.strip()[:160]}")

    ok = sum(1 for r in results if r["ok"])
    summary = {"rounds": args.rounds, "successes": ok,
               "validates": [r["validate"] for r in results if r["ok"]],
               "results": results}
    (TASK / "last_run.json").write_text(json.dumps(summary, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"successes {ok}/{args.rounds}; details in last_run.json")
    return 0 if ok == args.rounds else 1


if __name__ == "__main__":
    raise SystemExit(main())

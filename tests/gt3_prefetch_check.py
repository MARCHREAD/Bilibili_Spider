"""预取→解算 单轮冒烟检查（**不提交登录**，纯本地 + 极验）。

确认 biliwb 侧"由提交会话预取 gt/challenge/token，再交给解算器"的这条链路真的能
拿到 validate，并打印解算耗时（用于对照 token≈120s 的寿命预算）。

用法：python tests/gt3_prefetch_check.py [--budget 75]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from biliwb import constants as C
from biliwb import gt3
from biliwb.client import BiliClient


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=75)
    ap.add_argument("--source", default="main-fe")
    args = ap.parse_args()

    cli = BiliClient(cookie_file=None, min_delay=1.1, impersonate=C.IMPERSONATE)
    cli.bootstrap()

    body = cli.request_json(C.EP_CAPTCHA,
                            params={"source": args.source, "_": int(time.time() * 1000)},
                            soft=True, retries=1,
                            headers={"Referer": C.PASSPORT + "/login"})
    data = (body or {}).get("data") or {}
    gee = data.get("geetest") or {}
    print("prefetch:", json.dumps({"type": data.get("type"), "token": data.get("token"),
                                   "gt": gee.get("gt"), "challenge": gee.get("challenge")},
                                  ensure_ascii=False), flush=True)
    if not (gee.get("gt") and gee.get("challenge")):
        print("FAIL: 服务端未派 geetest 通道")
        return 2

    t0 = time.time()
    cap = gt3.solve_once(source=args.source, timeout=args.budget,
                         gt=gee["gt"], challenge=gee["challenge"], token=data["token"])
    age = round(time.time() - t0, 1)
    print("solve:", json.dumps({k: cap.get(k) for k in
                                ("ok", "validate", "score", "seconds", "http_used",
                                 "error", "verdict", "log_tail")}, ensure_ascii=False), flush=True)
    print(f"token_age_at_solve_end={age}s budget={args.budget}s "
          f"within_120s_lifetime={age < 120}")
    return 0 if cap.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Measure how long a passport captcha (gt/challenge/token) stays acceptable.

For each delay X: prefetch at T0, solve the *same* challenge at T0+X, submit with a
dummy username.  Because the captcha check runs before the credential check:
  -105 / -662  -> captcha rejected (expired / invalid)
  -629 / -400  -> captcha ACCEPTED (we reached the credential stage)

Usage: python tests/captcha_ttl.py [--delays 0,60,120]
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
from biliwb.accounts import rsa_encrypt
from biliwb.client import BiliClient

OUT = ROOT / "tests" / "_oracle"
OUT.mkdir(exist_ok=True)
DUMMY = "19900000009"


def prefetch(cli: BiliClient, source: str = "main-fe") -> dict:
    body = cli.request_json(
        f"{C.PASSPORT}/x/passport-login/captcha",
        params={"source": source, "_": int(time.time() * 1000)}, soft=True, retries=1,
        headers={"Referer": C.PASSPORT + "/login"})
    d = (body or {}).get("data") or {}
    gg = d.get("geetest") or {}
    return {"type": d.get("type"), "token": d.get("token"),
            "gt": gg.get("gt"), "challenge": gg.get("challenge"), "ttl": (body or {}).get("ttl")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delays", default="0,60,120")
    args = ap.parse_args()
    delays = [int(x) for x in args.delays.split(",") if x.strip()]

    cli = BiliClient(cookie_file=None, min_delay=1.1, impersonate=C.IMPERSONATE)
    cli.bootstrap()

    out = []
    for x in delays:
        rec: dict = {"delay": x}
        t0 = time.time()
        pre = prefetch(cli)
        rec["prefetch"] = pre
        if not pre.get("gt"):
            rec["error"] = "no gt in prefetch"
            out.append(rec)
            continue
        if x:
            time.sleep(x)
        cap = gt3.solve_once(source="main-fe", gt=pre["gt"],
                             challenge=pre["challenge"], token=pre["token"])
        rec["solve"] = {k: cap.get(k) for k in
                        ("ok", "validate", "score", "seconds", "error", "verdict")}
        if not cap.get("ok"):
            rec["submit"] = {"skipped": "solve failed"}
            out.append(rec)
            print(json.dumps(rec, ensure_ascii=False), flush=True)
            continue
        body = cli.request_json(C.EP_LOGIN_KEY, params={"_": int(time.time() * 1000)},
                                soft=True, retries=1)
        d = (body or {}).get("data") or {}
        enc = rsa_encrypt(d["key"], f"{d['hash']}not-a-real-password-0000")
        resp = cli.request_json(C.EP_LOGIN, method="POST", data={
            "source": "main-fe", "username": DUMMY, "password": enc,
            "validate": cap["validate"], "seccode": cap["seccode"],
            "challenge": cap["challenge"], "token": cap["token"],
            "sns_platform": "", "sns_openid": "",
            "csrf": cli.cookie_dict().get("bili_jct", ""),
            "go_url": "https://www.bilibili.com/",
        }, soft=True, retries=0, headers={"Referer": C.WWW + "/"})
        code = int((resp or {}).get("code", -1))
        rec["submit"] = {"code": code, "message": (resp or {}).get("message"),
                         "captcha_accepted": code not in (-105, -662)}
        rec["token_age_at_submit"] = round(time.time() - t0, 1)
        out.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)

    (OUT / "ttl.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Captcha-acceptance oracle for the passport login chain.

Question: does bilibili's login endpoint accept a GT3 validate that was obtained
in a *different* session than the one that prefetched /x/passport-login/captcha?

This never touches a real account: it submits a well-formed but dummy username
together with a deliberately wrong password.  A captcha rejection surfaces as
-105/-662 long before the credential check, so the returned code tells us whether
the captcha was accepted (-400 = credentials checked = captcha passed).

Usage: python tests/login_oracle.py [--with-solver]
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
from biliwb.accounts import LOGIN_CODE_HINT, rsa_encrypt
from biliwb.client import BiliClient

DUMMY_USER = "19900000000"
DUMMY_PASS = "not-a-real-password-0000"
SOURCE = "main-fe"

OUT = ROOT / "tests" / "_oracle"
OUT.mkdir(exist_ok=True)


def note(*a) -> None:
    print(*a, flush=True)


def new_client() -> BiliClient:
    cli = BiliClient(cookie_file=None, min_delay=1.1, impersonate=C.IMPERSONATE)
    cli.bootstrap()
    cli.warmup()
    cli.gen_ticket()
    return cli


def rsa_for(cli: BiliClient) -> str:
    body = cli.request_json(C.EP_LOGIN_KEY, params={"_": int(time.time() * 1000)},
                            soft=True, retries=1)
    data = (body or {}).get("data") or {}
    pubkey, salt = data.get("key"), data.get("hash")
    if not pubkey or not salt:
        raise RuntimeError(f"no rsa key: {body}")
    return rsa_encrypt(pubkey, f"{salt}{DUMMY_PASS}")


def submit(cli: BiliClient, username: str, encrypted: str, cap: dict | None) -> dict:
    payload = {
        "source": SOURCE,
        "username": username,
        "password": encrypted,
        "sns_platform": "",
        "sns_openid": "",
        "csrf": cli.cookie_dict().get("bili_jct", ""),
        "go_url": "https://www.bilibili.com/",
    }
    if cap:
        payload.update({
            "validate": cap["validate"],
            "seccode": cap["seccode"],
            "challenge": cap["challenge"],
            "token": cap["token"],
        })
    t0 = time.time()
    resp = cli.request_json(C.EP_LOGIN, method="POST", data=payload, soft=True, retries=0,
                            headers={"Referer": C.WWW + "/"})
    el = time.time() - t0
    code = int((resp or {}).get("code", -1))
    return {
        "code": code,
        "message": (resp or {}).get("message"),
        "hint": LOGIN_CODE_HINT.get(code, ""),
        "data": {k: v for k, v in ((resp or {}).get("data") or {}).items()
                 if k in ("status", "url", "refresh_token", "timestamp")},
        "seconds": round(el, 2),
        "sent_fields": sorted(payload),
    }


def prefetch(cli: BiliClient, source: str) -> dict:
    ts = int(time.time() * 1000)
    body = cli.request_json(
        f"{C.PASSPORT}/x/passport-login/captcha",
        params={"source": source, "_": ts}, soft=True, retries=1,
        headers={"Referer": C.PASSPORT + "/login"},
    )
    data = (body or {}).get("data") or {}
    return {
        "type": data.get("type"),
        "token": data.get("token"),
        "gt": (data.get("geetest") or {}).get("gt"),
        "challenge": (data.get("geetest") or {}).get("challenge"),
        "raw_keys": sorted(data),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-solver", action="store_true",
                    help="also run the two full solver chains (~40s)")
    ap.add_argument("--username", default=DUMMY_USER)
    args = ap.parse_args()

    report: dict = {"username": args.username, "source": SOURCE}

    # ---- Step 0: does the server check the captcha before the credentials? ----
    cli = new_client()
    note("[0] probing credential/captcha check order (no captcha fields sent)")
    r0 = submit(cli, args.username, rsa_for(cli), cap=None)
    note("    ->", json.dumps(r0, ensure_ascii=False))
    report["order_probe_no_captcha"] = r0

    if not args.with_solver:
        (OUT / "oracle.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
        return 0

    # ---- Step 1: variant A = solver prefetches its own challenge (current prod) ----
    note("[A] solver-prefetched challenge, submitted by the account session")
    cliA = new_client()
    encA = rsa_for(cliA)
    capA = gt3.solve_once(source=SOURCE)
    note("    solve:", json.dumps({k: capA.get(k) for k in
                                   ("ok", "challenge", "token", "validate", "seccode",
                                    "score", "seconds", "error", "verdict")}, ensure_ascii=False))
    if capA.get("ok"):
        rA = submit(cliA, args.username, encA, capA)
    else:
        rA = {"skipped": "solve failed", "error": capA.get("error"), "verdict": capA.get("verdict")}
    note("    ->", json.dumps(rA, ensure_ascii=False))
    report["variant_A_solver_session"] = {"captcha": {k: capA.get(k) for k in
                                                      ("ok", "gt", "challenge", "token",
                                                       "validate", "score", "seconds",
                                                       "error", "verdict")},
                                          "submit": rA}

    # ---- Step 2: variant B = challenge prefetched by the submitting session ----
    note("[B] challenge prefetched by the account session, one session end to end")
    cliB = new_client()
    encB = rsa_for(cliB)
    pre = prefetch(cliB, SOURCE)
    note("    prefetch:", json.dumps(pre, ensure_ascii=False))
    capB = gt3.solve_once(source=SOURCE, gt=pre["gt"], challenge=pre["challenge"],
                          token=pre["token"])
    note("    solve:", json.dumps({k: capB.get(k) for k in
                                   ("ok", "challenge", "token", "validate", "seccode",
                                    "score", "seconds", "error", "verdict")}, ensure_ascii=False))
    if capB.get("ok"):
        rB = submit(cliB, args.username, encB, capB)
    else:
        rB = {"skipped": "solve failed", "error": capB.get("error"), "verdict": capB.get("verdict")}
    note("    ->", json.dumps(rB, ensure_ascii=False))
    report["variant_B_same_session"] = {"prefetch": pre,
                                        "captcha": {k: capB.get(k) for k in
                                                    ("ok", "gt", "challenge", "token",
                                                     "validate", "score", "seconds",
                                                     "error", "verdict")},
                                        "submit": rB}

    (OUT / "oracle.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    note("saved tests/_oracle/oracle.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

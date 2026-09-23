"""Fetch the passport SPA bundle and mine the captcha wiring locally.

Stage 1: fetch asset (live egress, GET only).
Stage 2: local static mining, no egress.
Prints a readable mining report to stderr; machine JSON on stdout.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from curl_cffi import requests

TASK_DIR = Path(__file__).resolve().parent
RAW = TASK_DIR / "raw"
RAW.mkdir(parents=True, exist_ok=True)
IMPERSONATE = "chrome146"

BUNDLE_URL = "https://s1.hdslb.com/bfs/static/2233-monorepo/passport/static/js/index.ed509056.js"

NEEDLES = [
    "geetest",
    "gt.js",
    "gt.0.4.9",
    "static.geetest.com",
    "geetest_challenge",
    "geetest_validate",
    "geetest_seccode",
    "challenge",
    "validate",
    "seccode",
    "captcha",
    "risk",
    "bili-captcha",
    "bilicaptcha",
    "gt_",
    "register-slide",
    "fullpage",
    "slide.",
    "gettype.php",
    "get.php",
    "ajax.php",
    "/x/passport-login/",
    "/x/passport-login/web/",
    "buvid",
    "bili_jct",
    "salted",
    "public_key",
    "rsa",
    "encrypt",
]


def note(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def fetch(url: str, name: str) -> str:
    session = requests.Session(impersonate=IMPERSONATE)
    time.sleep(0.4)
    resp = session.get(url, headers={"Referer": "https://passport.bilibili.com/login"}, timeout=40)
    body = resp.text
    (RAW / name).write_text(body, encoding="utf-8", errors="replace")
    with (TASK_DIR / "network.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {"probe": name, "url": url, "status": resp.status_code, "len": len(body)},
                ensure_ascii=False,
            )
            + "\n"
        )
    note(f"[fetch] {name} {resp.status_code} {len(body)}B")
    return body


def windows(text: str, needle: str, width: int = 200, limit: int = 6) -> list[str]:
    out, seen = [], set()
    for m in re.finditer(re.escape(needle), text, re.I):
        start = max(0, m.start() - width)
        snippet = text[start : m.end() + width].replace("\n", " ")
        key = snippet[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(f"@{m.start()} ...{snippet}...")
        if len(out) >= limit:
            break
    return out


def main() -> int:
    bundle = fetch(BUNDLE_URL, "index.ed509056.js")
    report: dict = {"bundle_len": len(bundle), "hits": {}, "urls": [], "windows": {}}

    for needle in NEEDLES:
        n = len(re.findall(re.escape(needle), bundle, re.I))
        report["hits"][needle] = n

    report["urls"] = sorted(set(re.findall(r"[\"'`](/x/passport-login/[A-Za-z0-9_/\-]+)", bundle)))
    report["assets"] = sorted(set(re.findall(r"https?://[A-Za-z0-9._\-]+/[A-Za-z0-9._/\-]*\.js", bundle)))[:40]
    report["chunks"] = sorted(set(re.findall(r"[\"'`](\./js/[A-Za-z0-9._\-]+\.js)", bundle)))[:40]

    for needle in (
        "static.geetest.com",
        "gettype.php",
        "geetest_challenge",
        "geetest_validate",
        "geetest_seccode",
        "register-slide",
        "captcha",
        "risk",
        "buvid",
        "public_key",
    ):
        w = windows(bundle, needle)
        if w:
            report["windows"][needle] = w

    (TASK_DIR / "static_findings.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    note("=== hit counts ===")
    for k, v in report["hits"].items():
        if v:
            note(f"  {k}: {v}")
    note("=== passport routes in bundle ===")
    for u in report["urls"]:
        note(f"  {u}")
    note("=== external .js assets ===")
    for a in report["assets"]:
        note(f"  {a}")
    note("=== chunk paths ===")
    for c in report["chunks"]:
        note(f"  {c}")
    note("=== selected windows ===")
    for k, ws in report["windows"].items():
        note(f"--- {k} ---")
        for w in ws:
            note(f"  {w}")

    print(json.dumps({k: report[k] for k in ("bundle_len", "hits", "urls", "assets", "chunks")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

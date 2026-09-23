"""Read-only wire probe for the bilibili login captcha chain.

Scope: GET only. No login, no account state, no captcha answer submission.
Prints human-readable deltas to stderr; machine JSON summary on stdout.
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

IMPERSONATE = "chrome146"  # locked to installed curl_cffi max, not live Chrome major
HOME = "https://www.bilibili.com/?spm_id_from=333.1007.0.0"

NETWORK_LOG = TASK_DIR / "network.jsonl"
_summary: dict = {"impersonate": IMPERSONATE, "probes": []}


def note(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def log_request(entry: dict) -> None:
    with NETWORK_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def save(name: str, text: str) -> Path:
    path = RAW / name
    path.write_text(text, encoding="utf-8", errors="replace")
    return path


def probe(session: requests.Session, name: str, url: str, headers: dict | None = None, save_as: str | None = None):
    time.sleep(0.4)
    resp = session.get(url, headers=headers, timeout=25)
    body = resp.text
    path = save(save_as, body) if save_as else None
    entry = {
        "probe": name,
        "url": url,
        "status": resp.status_code,
        "content_type": resp.headers.get("content-type"),
        "len": len(body),
        "sent_cookie_header": session.headers.get("Cookie") or "",
        "set_cookie_names": [c.split("=", 1)[0] for c in resp.headers.get_list("set-cookie")],
        "saved": str(path) if path else None,
    }
    log_request(entry)
    _summary["probes"].append(entry)
    note(f"[{name}] {resp.status_code} {len(body)}B ct={entry['content_type']} -> {path}")
    return resp, body


def main() -> int:
    session = requests.Session(impersonate=IMPERSONATE)
    session.headers.update(
        {
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        }
    )

    # --- P1: homepage (the URL the user handed us) -------------------------
    resp, html = probe(session, "home", HOME, headers={"Referer": "https://www.bilibili.com/"}, save_as="home.html")

    markers = {
        "geetest": len(re.findall(r"geetest", html, re.I)),
        "captcha": len(re.findall(r"captcha", html, re.I)),
        "gt\\.js": len(re.findall(r"gt\.js", html, re.I)),
        "passport": len(re.findall(r"passport", html, re.I)),
    }
    _summary["home_markers"] = markers
    note(f"[home] markers={markers}")

    # --- P2: captcha init (the canonical verifier bootstrap) ---------------
    resp, cap = probe(
        session,
        "captcha_init",
        "https://passport.bilibili.com/x/passport-login/captcha?source=main-fe-header",
        headers={"Referer": "https://www.bilibili.com/", "Origin": "https://www.bilibili.com"},
        save_as="captcha_init.json",
    )
    try:
        cap_json = json.loads(cap)
        _summary["captcha_init"] = cap_json
        note("[captcha_init] " + json.dumps(cap_json, ensure_ascii=False)[:600])
    except Exception as exc:  # noqa: BLE001
        cap_json = None
        note(f"[captcha_init] non-JSON body: {exc}")

    # --- P3: alternate init sources ---------------------------------------
    for src in ("main-fe-header", "blog"):
        probe(
            session,
            f"captcha_init_src_{src}",
            f"https://passport.bilibili.com/x/passport-login/captcha?source={src}",
            headers={"Referer": "https://www.bilibili.com/"},
            save_as=f"captcha_init_{src}.json",
        )

    # --- P4: login page HTML ----------------------------------------------
    resp, login_html = probe(
        session,
        "login_page",
        "https://passport.bilibili.com/login",
        headers={"Referer": "https://www.bilibili.com/"},
        save_as="login_page.html",
    )
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', login_html)
    _summary["login_scripts"] = scripts
    note("[login_page] scripts: " + ", ".join(scripts))
    for kw in ("geetest", "captcha", "risk", "verify", "slide"):
        note(f"[login_page] '{kw}' hits={len(re.findall(kw, login_html, re.I))}")

    # --- P5: geetest GT3 register (only if gt/challenge exist) --------------
    gt = None
    if isinstance(cap_json, dict):
        gt = (cap_json.get("data") or {}).get("geetest") or {}
    if gt.get("gt"):
        cb = f"geetest_{int(time.time() * 1000)}"
        probe(
            session,
            "gt3_gettype",
            f"https://api.geetest.com/gettype.php?gt={gt['gt']}&callback={cb}",
            headers={"Referer": "https://passport.bilibili.com/"},
            save_as="gt3_gettype.txt",
        )
    else:
        note("[gt3_gettype] skipped: no data.geetest.gt in captcha init")

    with (TASK_DIR / "probe_summary.json").open("w", encoding="utf-8") as fh:
        json.dump(_summary, fh, ensure_ascii=False, indent=2)
    print(json.dumps(_summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

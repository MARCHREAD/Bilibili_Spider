"""Control probes: GT3 /get.php register hop, source=main-fe schema, image-channel negative control.

GET only. No login, no captcha answer submission, no account state.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from curl_cffi import requests

TASK = Path(__file__).resolve().parent
RAW = TASK / "raw"
IMPERSONATE = "chrome146"


def note(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def call(session, name, url, headers=None, save_as=None):
    time.sleep(0.4)
    r = session.get(url, headers=headers, timeout=25)
    body = r.text
    path = RAW / save_as if save_as else None
    if path:
        path.write_text(body, encoding="utf-8", errors="replace")
    with (TASK / "network.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"probe": name, "url": url, "status": r.status_code, "len": len(body)}) + "\n")
    note(f"[{name}] {r.status_code} {len(body)}B ct={r.headers.get('content-type')} -> {path}")
    return body


def main() -> int:
    s = requests.Session(impersonate=IMPERSONATE)
    s.headers.update({"Accept-Language": "zh-CN,zh;q=0.9", "Referer": "https://passport.bilibili.com/login"})
    out: dict = {}

    # --- A. component-default source schema -------------------------------
    a1 = json.loads(call(s, "captcha_main-fe_1", "https://passport.bilibili.com/x/passport-login/captcha?source=main-fe"))
    a2 = json.loads(call(s, "captcha_main-fe_2", "https://passport.bilibili.com/x/passport-login/captcha?source=main-fe"))
    out["main_fe_rounds"] = [a1.get("data"), a2.get("data")]
    note(f"[schema] keys={sorted(a1.get('data', {}).keys())} "
         f"gt_same={a1['data']['geetest']['gt'] == a2['data']['geetest']['gt']} "
         f"challenge_same={a1['data']['geetest']['challenge'] == a2['data']['geetest']['challenge']} "
         f"token_same={a1['data']['token'] == a2['data']['token']}")

    gt = a1["data"]["geetest"]["gt"]
    challenge = a1["data"]["geetest"]["challenge"]

    # --- B. GT3 second hop: get.php (what the vendored loader calls next) --
    cb = f"geetest_{int(time.time() * 1000)}"
    body = call(
        s,
        "gt3_get",
        f"https://api.geetest.com/get.php?gt={gt}&challenge={challenge}&lang=zh-cn&pt=0&client_type=web&callback={cb}",
        headers={"Referer": "https://passport.bilibili.com/login"},
        save_as="gt3_get.txt",
    )
    m = re.search(r"\((\{.*\})\)", body, re.S)
    if m:
        try:
            out["gt3_get"] = json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            out["gt3_get_raw"] = body[:800]
    note(f"[gt3_get] {body[:500]}")

    # --- C. image channel negative control (no server-issued token) -------
    body = call(
        s,
        "recaptcha_img_no_token",
        f"https://api.bilibili.com/x/recaptcha/img?_={int(time.time()*1000)}",
        headers={"Referer": "https://passport.bilibili.com/login"},
        save_as="recaptcha_img_no_token.txt",
    )
    try:
        out["recaptcha_img_no_token"] = json.loads(body)
    except Exception:  # noqa: BLE001
        out["recaptcha_img_no_token"] = body[:300]
    note(f"[recaptcha_img_no_token] {body[:300]}")

    # --- D. same token, bogus value: does the server rotate/consume? ------
    body = call(
        s,
        "recaptcha_img_bogus_token",
        f"https://api.bilibili.com/x/recaptcha/img?_={int(time.time()*1000)}&token=deadbeefdeadbeefdeadbeefdeadbeef",
        headers={"Referer": "https://passport.bilibili.com/login"},
        save_as="recaptcha_img_bogus_token.txt",
    )
    try:
        out["recaptcha_img_bogus_token"] = json.loads(body)
    except Exception:  # noqa: BLE001
        out["recaptcha_img_bogus_token"] = body[:300]
    note(f"[recaptcha_img_bogus_token] {body[:300]}")

    (TASK / "control_probes.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only probe: what does passport captcha init return right now?

GET only. No login, no captcha answer submission to bilibili.
"""
from __future__ import annotations

import json
import time

from curl_cffi import requests as cffi

IMP = "chrome"

def show(tag: str, s) -> None:
    ts = int(time.time() * 1000)
    r = s.get(f"https://passport.bilibili.com/x/passport-login/captcha?source=main-fe&_={ts}", timeout=25)
    print(f"--- {tag} status={r.status_code} len={len(r.text)}")
    try:
        body = r.json()
    except Exception:
        print("    non-json:", r.text[:200])
        return
    print("    top keys:", sorted(body))
    d = body.get("data") or {}
    print("    data keys:", sorted(d))
    print("    data:", json.dumps({k: (v if not isinstance(v, dict) else sorted(v)) for k, v in d.items()}, ensure_ascii=False))
    print("    set-cookie:", r.headers.get("set-cookie", "")[:300])
    for k, v in s.cookies.items():
        print(f"    cookie {k} = {str(v)[:40]}")


def main() -> None:
    s1 = cffi.Session(impersonate=IMP)
    s1.headers.update({"Accept-Language": "zh-CN,zh;q=0.9",
                       "Referer": "https://passport.bilibili.com/login"})
    show("fresh-session", s1)

    s2 = cffi.Session(impersonate=IMP)
    s2.headers.update({"Accept-Language": "zh-CN,zh;q=0.9",
                       "Referer": "https://www.bilibili.com/"})
    spi = s2.get("https://api.bilibili.com/x/frontend/finger/spi", timeout=25).json()
    print("spi:", json.dumps(spi)[:200])
    d = spi.get("data") or {}
    if d.get("b_3"):
        s2.cookies.set("buvid3", d["b_3"], domain=".bilibili.com")
        s2.cookies.set("buvid4", d["b_4"], domain=".bilibili.com")
    s2.headers["Referer"] = "https://passport.bilibili.com/login"
    show("buvid-session", s2)


if __name__ == "__main__":
    main()

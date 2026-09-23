"""抓 passport-h5 的 JS 并挖掘 /risk/verify 的验证方式与 API（只读 GET）。

用法：python tests/mine_passport_h5.py
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "tests" / "_riskverify" / "js"
OUT.mkdir(parents=True, exist_ok=True)

BASE = "https://s1.hdslb.com/bfs/static/2233-monorepo/passport-h5/static/js/"
FILES = ["index.933966bb.js", "622.622fc7ab.js"]

# 与验证方式直接相关的线索
KEYWORDS = ["safecenter", "sms", "tel", "verify_type", "tmp_token", "captcha",
            "exchange_cookie", "risk", "geetest", "recaptcha", "web/generic",
            "passport-login", "send", "check", "question"]


def fetch(sess, name: str) -> str:
    p = OUT / name
    if p.exists():
        return p.read_text(encoding="utf-8", errors="replace")
    r = sess.get(BASE + name, timeout=40)
    print(f"  GET {name} -> {r.status_code} {len(r.text)}B", flush=True)
    p.write_text(r.text, encoding="utf-8", errors="replace")
    return r.text


def main() -> int:
    from curl_cffi import requests as cffi

    sess = cffi.Session(impersonate="chrome")
    sess.headers.update({"Referer": "https://passport.bilibili.com/"})

    print("== 抓取 ==", flush=True)
    texts = {n: fetch(sess, n) for n in FILES}

    report: dict = {}
    for name, t in texts.items():
        paths = sorted(set(re.findall(r"[\"'](/x/[a-zA-Z0-9_\-/]{3,90})[\"']", t)))
        routes = sorted(set(re.findall(r"path:\s*[\"']([^\"']{2,60})[\"']", t)))
        report[name] = {"len": len(t), "x_paths": paths, "routes": routes}

    print("\n== /x/ 接口路径 ==")
    for name, info in report.items():
        print(f"--- {name}")
        for p in info["x_paths"]:
            print("   ", p)

    print("\n== 前端路由 ==")
    for name, info in report.items():
        if info["routes"]:
            print(f"--- {name}: {info['routes']}")

    # 逐关键词给上下文
    print("\n== 关键词上下文 ==")
    for name, t in texts.items():
        for kw in KEYWORDS:
            ms = list(re.finditer(re.escape(kw), t))
            if not ms:
                continue
            print(f"--- {name} :: {kw} ({len(ms)} hits)")
            shown = 0
            for m in ms:
                s = max(0, m.start() - 200)
                snip = t[s:m.start() + 200].replace("\n", " ")
                # 只打印含接口路径或明显语义的片段
                if "/x/" in snip or "verify" in snip or "sms" in snip:
                    print("    ..." + snip + "...")
                    shown += 1
                    if shown >= 2:
                        break

    (OUT.parent / "mine.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

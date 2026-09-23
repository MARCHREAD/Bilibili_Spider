"""抓 /h5-app/passport/risk/verify 页面：它到底要求什么验证？能否协议化？

只读 GET。url 里的 tmp_token 是上一次登录尝试服务端下发的（可能已过期），
但页面骨架/JS 引用与 token 无关，足以判断验证方式。

用法：python tests/probe_riskverify_h5.py [--tmp-token TOKEN] [--request-id ID]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "tests" / "_riskverify"
OUT.mkdir(exist_ok=True)

DEFAULT_TOKEN = "81543bf464e0ad6edf9b7ef591572192"
DEFAULT_REQUEST_ID = "6fce4b5b1c764260b9a5184c8b860880"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tmp-token", default=DEFAULT_TOKEN)
    ap.add_argument("--request-id", default=DEFAULT_REQUEST_ID)
    args = ap.parse_args()

    from curl_cffi import requests as cffi

    q = urllib.parse.urlencode({
        "gourl": "https://www.bilibili.com/",
        "request_id": args.request_id,
        "source": "risk",
        "tmp_token": args.tmp_token,
    })
    url = f"https://passport.bilibili.com/h5-app/passport/risk/verify?{q}"
    print("GET", url, flush=True)

    s = cffi.Session(impersonate="chrome")
    s.headers.update({"Accept-Language": "zh-CN,zh;q=0.9",
                      "Referer": "https://passport.bilibili.com/"})
    r = s.get(url, timeout=30, allow_redirects=True)
    print(f"status={r.status_code} final_url={r.url} len={len(r.text)} "
          f"ctype={r.headers.get('content-type')}", flush=True)
    print("set-cookie:", (r.headers.get("set-cookie") or "")[:300], flush=True)

    html = r.text
    (OUT / "verify_page.html").write_text(html, encoding="utf-8", errors="replace")

    scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)
    links = re.findall(r'<link[^>]+href="([^"]+)"', html)
    print("\n--- scripts ---")
    for x in scripts:
        print("  ", x)
    print("--- links ---")
    for x in links:
        print("  ", x)

    # 页面内联文案：能直接看出要求什么验证
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    print("\n--- 可见文本 ---")
    print(text[:1500])

    # 内联 JSON（__INITIAL_STATE__ 之类）
    for m in re.finditer(r"window\.(__\w+|\w*INITIAL\w*)\s*=", html):
        print("\n--- inline state:", m.group(1))

    print("\n--- API 路径线索（页面内出现的 /x/ 接口）---")
    for path in sorted(set(re.findall(r"[\"'](/?x/[a-zA-Z0-9_\-/]{4,80})[\"']", html))):
        print("  ", path)

    (OUT / "probe.json").write_text(json.dumps(
        {"status": r.status_code, "final_url": r.url, "scripts": scripts,
         "links": links, "visible_text": text[:3000]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

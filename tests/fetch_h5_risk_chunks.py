"""抓 /risk/verify 的懒加载 chunk，确定 status=2 到底要求哪种验证（只读 GET）。

用法：python tests/fetch_h5_risk_chunks.py
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

JSDIR = ROOT / "tests" / "_riskverify" / "js"
BASE = "https://s1.hdslb.com/bfs/static/2233-monorepo/passport-h5/static/js/async/"

# /risk/verify 组件的依赖 chunk（从路由定义里读出来的）
TARGET_IDS = ["6493", "7975", "4632", "9615", "5043", "865", "3652", "9212"]


def main() -> int:
    from curl_cffi import requests as cffi

    index = (JSDIR / "index.933966bb.js").read_text(encoding="utf-8", errors="replace")

    # webpack 文件名函数：l.u=function(e){return"static/js/async/"+e+"."+({id:"hash"}[e])+".js"}
    # 直接定位映射对象体，避免正则被转义层数坑到
    mapping: dict[str, str] = {}
    i = index.find("static/js/async/")
    if i > 0:
        j = index.find("}", i)
        body = index[index.find("{", i) + 1:j]
        mapping = dict(re.findall(r'(\d+):"([0-9a-f]+)"', body))
    print(f"chunk 映射解析到 {len(mapping)} 项", flush=True)
    for probe in TARGET_IDS:
        if probe in mapping:
            print(f"    {probe} -> {mapping[probe]}", flush=True)

    sess = cffi.Session(impersonate="chrome")
    sess.headers.update({"Referer": "https://passport.bilibili.com/"})

    found = {}
    for cid in TARGET_IDS:
        h = mapping.get(cid)
        if not h:
            print(f"  chunk {cid}: 映射缺失，跳过")
            continue
        name = f"{cid}.{h}.js"
        p = JSDIR / name
        if not p.exists():
            r = sess.get(BASE + name, timeout=40)
            print(f"  GET {name} -> {r.status_code} {len(r.text)}B", flush=True)
            p.write_text(r.text, encoding="utf-8", errors="replace")
        found[cid] = name

    print("\n== 在 risk/verify 相关 chunk 里找验证方式与接口 ==")
    KWS = ["safecenter", "sms", "face", "question", "verify_type", "tmp_token",
           "risk/verify", "exchange_cookie", "captcha", "sendSms", "checkSms",
           "ahead", "verifyWay", "way", "geetest"]
    for cid, name in found.items():
        t = (JSDIR / name).read_text(encoding="utf-8", errors="replace")
        paths = sorted(set(re.findall(r"[\"'](/x/[a-zA-Z0-9_\-/{}.]{3,90})[\"']", t)))
        hits = {k: len(re.findall(re.escape(k), t)) for k in KWS}
        hits = {k: v for k, v in hits.items() if v}
        if paths or hits:
            print(f"\n--- {name}  paths={paths[:14]}")
            print(f"     keywords={hits}")

    # 打印含中文的验证方式文案（i18n 里 zh 段）
    print("\n== 中文验证相关文案 ==")
    for cid, name in found.items():
        t = (JSDIR / name).read_text(encoding="utf-8", errors="replace")
        for kw in ("安全验证", "短信验证", "人脸", "安全提问", "验证码", "验证方式",
                   "身份验证", "申诉", "手机号"):
            for m in re.finditer(re.escape(kw), t):
                s = max(0, m.start() - 80)
                print(f"  [{name}] ...{t[s:m.start() + 80]}...".replace("\n", " "))
                break

    (JSDIR.parent / "chunks.json").write_text(
        json.dumps({"mapping_used": {k: found.get(k) for k in TARGET_IDS}},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

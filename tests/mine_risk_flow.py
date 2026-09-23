"""提取 status=2 短信验证流程的确切参数与调用顺序（只读，本地分析）。

用法：python tests/mine_risk_flow.py
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = [
    ROOT / "js_reverse_cache/tasks/bili-login-captcha/raw/chunks/409.968ce5e0.js",
    ROOT / "js_reverse_cache/tasks/bili-login-captcha/raw/chunks/86.7f85abb2.js",
    ROOT / "tests/_riskverify/js/9212.003b7c38.js",
]
ENDPOINTS = ["/x/safecenter/captcha/pre", "/x/safecenter/common/sms/send",
             "/x/safecenter/sec/verify", "/x/passport-login/web/exchange_cookie",
             "/x/safecenter/login/tel/verify", "/x/safecenter/user/info"]


def show(t: str, label: str, kw: str, before: int = 200, after: int = 700,
         limit: int = 2) -> None:
    ms = list(re.finditer(re.escape(kw), t))
    if not ms:
        return
    print(f"\n--- [{label}] {kw}  ({len(ms)} hits)")
    for m in ms[:limit]:
        s = max(0, m.start() - before)
        print("   ..." + t[s:m.start() + after].replace("\n", " ") + "...")


def main() -> int:
    for f in FILES:
        if not f.exists():
            print(f"missing: {f}")
            continue
        t = f.read_text(encoding="utf-8", errors="replace")
        print(f"\n================ {f.name} ({len(t)}B) ================")
        for ep in ENDPOINTS:
            show(t, f.name, ep, limit=1)
        # 调用点：导出名调用（webpack 压缩后形如 .CX( / .v$( / .nU( ）
        for call in (".v$(", ".nU(", ".CX(", ".YF(", ".Og(", ".cl("):
            show(t, f.name, call, before=260, after=260, limit=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

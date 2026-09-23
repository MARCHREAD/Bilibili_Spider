"""定位 verify 超时：直接测底层 BiliClient 的 bootstrap / nav 耗时。"""

from __future__ import annotations

import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from biliwb import constants as C  # noqa: E402
from biliwb.client import BiliClient  # noqa: E402

SESSION = ROOT / "data" / "session.txt"


def step(label: str, fn):
    t0 = time.time()
    try:
        out = fn()
        print(f"  {label:<28} OK   {time.time() - t0:6.1f}s  {str(out)[:90]}", file=sys.stderr)
        return out
    except Exception as exc:
        print(f"  {label:<28} FAIL {time.time() - t0:6.1f}s  {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return None


def main() -> int:
    cookie = SESSION.read_text(encoding="utf-8").strip() if SESSION.exists() else ""
    print(f"cookie 长度={len(cookie)} 片段={cookie[:30]}...", file=sys.stderr)

    print("\n[A] 导入已保存 cookie，不额外 bootstrap", file=sys.stderr)
    cli = BiliClient(min_delay=1.0, retries=1, timeout=20, verbose=True)
    cli.import_cookies(cookie)
    step("nav(refresh=True)", lambda: (cli.nav(refresh=True) or {}).get("uname"))

    print("\n[B] 全新会话（无 cookie）直接 nav", file=sys.stderr)
    cli2 = BiliClient(min_delay=1.0, retries=1, timeout=20)
    step("nav(refresh=True)", lambda: (cli2.nav(refresh=True) or {}).get("isLogin"))

    print("\n[C] 全新会话先 bootstrap 再 nav", file=sys.stderr)
    cli3 = BiliClient(min_delay=1.0, retries=1, timeout=20)
    step("bootstrap()", lambda: len(cli3.bootstrap()))
    step("nav(refresh=True)", lambda: (cli3.nav(refresh=True) or {}).get("isLogin"))

    print("\n[D] 带 cookie 会话：bootstrap + nav 计时", file=sys.stderr)
    cli4 = BiliClient(min_delay=1.0, retries=1, timeout=20)
    cli4.import_cookies(cookie)
    step("bootstrap()", lambda: len(cli4.bootstrap()))
    step("gen_ticket()", lambda: bool(cli4.gen_ticket()))
    nav = step("nav(refresh=True)", lambda: cli4.nav(refresh=True))
    if isinstance(nav, dict):
        print(f"    isLogin={nav.get('isLogin')} uname={nav.get('uname')} mid={nav.get('mid')}",
              file=sys.stderr)

    print(f"\nhttp_calls={cli4.http_calls}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

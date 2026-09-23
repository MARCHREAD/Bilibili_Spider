"""软风控耐久验证：连续真实搜索请求，统计最终失败率与重试轮数。

模拟用户"页数上去"的批量场景：请求数一多，软风控命中的**绝对次数**就上去了，
旧实现（4 轮、原地退避、窄检测）会在其中几次耗尽重试。

这里走**完整的 request_json**（含新的独立预算 + 自愈），统计：
  * 最终失败次数（目标 0）
  * 每请求实际尝试轮数
  * 软风控共命中多少次

用法：python tests/verify_soft_risk_endurance.py [--account 1] [--rounds 12]
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
from biliwb.accounts import AccountPool
from biliwb.errors import SoftRisk
from biliwb.store import Store

OUT = ROOT / "tests" / "_paging"
OUT.mkdir(exist_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", type=int, default=None)
    ap.add_argument("--rounds", type=int, default=12)
    ap.add_argument("--pages", default="1,5,10,15,20,25,30,2,7,12,33,34")
    args = ap.parse_args()

    store = Store(ROOT / "data" / "biliwb.db")
    pool = AccountPool(store, data_dir=ROOT / "data")
    aid = args.account or pool.pick()
    cli = pool.client(aid)          # 现在创建时会自动 bootstrap
    pages = [int(x) for x in args.pages.split(",")]
    print(f"account={aid} rounds={args.rounds} soft_risk_retries={cli.soft_risk_retries}",
          flush=True)

    base_params = {"search_type": "video", "keyword": "原神", "order": "totalrank",
                   "page_size": 30, "duration": 0, "from_source": "",
                   "web_location": 1430654}

    rows = []
    t0 = time.time()
    for i in range(args.rounds):
        page = pages[i % len(pages)]
        before = cli.http_calls
        rec = {"i": i + 1, "page": page}
        try:
            data = cli.request_json(C.EP_SEARCH_TYPE, params=dict(base_params, page=page),
                                    wbi=True,
                                    headers={"Referer": "https://search.bilibili.com/"})
            n = len((data or {}).get("result") or [])
            rec.update({"ok": True, "result_len": n,
                        "api_page": (data or {}).get("page")})
        except SoftRisk as exc:
            rec.update({"ok": False, "error": f"SoftRisk({exc.attempts} 轮): {exc}"})
        except Exception as exc:  # noqa: BLE001
            rec.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        rec["http_cost"] = cli.http_calls - before
        rows.append(rec)
        print(f"  #{rec['i']:<3} page={page:<3} {'OK' if rec.get('ok') else 'FAIL':<5} "
              f"len={rec.get('result_len')} http={rec['http_cost']} "
              f"{rec.get('error', '')[:60]}", flush=True)

    ok = sum(1 for r in rows if r.get("ok"))
    fail = len(rows) - ok
    # 每个请求至少 1 次 http；多出来的就是软风控/其他重试
    extra = sum(max(0, r["http_cost"] - 1) for r in rows)
    print("\n== 耐久结果 ==")
    print(f"  成功 {ok}/{len(rows)}，失败 {fail}")
    print(f"  额外重试的 http 次数 {extra}（= 软风控等命中后重试的次数）")
    print(f"  总耗时 {time.time() - t0:.0f}s, http_calls={cli.http_calls}")

    (OUT / f"endurance_{int(time.time())}.json").write_text(
        json.dumps({"account": aid, "ok": ok, "fail": fail, "extra_http": extra,
                    "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    store.close()
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

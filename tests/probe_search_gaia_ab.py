"""gaia 槽位对搜索接口软风控的交替 A/B 对照。

交替采样（A,B,A,B,...）以消除"时间趋势/会话信誉漂移"这一混淆变量：
  A = 现状（不带 gaia 槽位）
  B = 带 gaia 槽位

同一 client / 同一间隔 / 同一 page，唯一自变量是 gaia 槽位。

用法：python tests/probe_search_gaia_ab.py [--rounds 10]
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
from biliwb.client import gaia_slots
from biliwb.store import Store

OUT = ROOT / "tests" / "_paging"
OUT.mkdir(exist_ok=True)

BASE = {
    "search_type": "video", "keyword": "原神", "order": "totalrank", "page": 1,
    "page_size": 30, "duration": 0, "from_source": "", "web_location": 1430654,
}


def probe(cli, with_gaia: bool) -> str:
    params = dict(BASE)
    if with_gaia:
        params.update(gaia_slots())
    try:
        body = cli.request_json(C.EP_SEARCH_TYPE, params=params, wbi=True, soft=True,
                                retries=0,
                                headers={"Referer": "https://search.bilibili.com/"})
    except Exception as exc:  # noqa: BLE001
        return f"ERROR {type(exc).__name__}"
    data = (body or {}).get("data")
    if isinstance(data, dict):
        if "v_voucher" in data:
            return "SOFT-RISK"
        res = data.get("result")
        return f"OK result={len(res)}" if isinstance(res, list) and res else "OK-empty"
    return "ERROR shape"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", type=int, default=None)
    ap.add_argument("--rounds", type=int, default=10)
    args = ap.parse_args()

    store = Store(ROOT / "data" / "biliwb.db")
    pool = AccountPool(store, data_dir=ROOT / "data")
    aid = args.account or pool.pick()
    api = pool.api(aid)
    cli = pool.client(aid)
    cli.bootstrap()
    cli.gen_ticket()

    print(f"account={aid} rounds={args.rounds}（交替 A=无gaia / B=+gaia）", flush=True)
    res = {"A_no_gaia": [], "B_with_gaia": []}
    for i in range(args.rounds):
        for arm, with_gaia in (("A_no_gaia", False), ("B_with_gaia", True)):
            v = probe(cli, with_gaia)
            res[arm].append(v)
            print(f"  round{i + 1} {arm:<12} -> {v}", flush=True)

    print("\n== 交替 A/B 结果 ==")
    out = {}
    for arm, vals in res.items():
        soft = sum(1 for v in vals if v == "SOFT-RISK")
        out[arm] = {"soft_risk": soft, "n": len(vals),
                    "rate": round(soft / max(1, len(vals)), 2), "verdicts": vals}
        print(f"  {arm:<12} {soft}/{len(vals)}  rate={out[arm]['rate']}")

    a, b = out["A_no_gaia"]["rate"], out["B_with_gaia"]["rate"]
    print(f"\n  结论：gaia 槽位把软风控命中率从 {a:.0%} 降到 {b:.0%}"
          if b < a else f"\n  结论：本轮到 {a:.0%} vs {b:.0%}，未见 gaia 明显收益")

    (OUT / f"gaia_ab_{int(time.time())}.json").write_text(
        json.dumps({"account": aid, "report": out}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

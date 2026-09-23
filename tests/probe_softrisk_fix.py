"""软风控自愈实验：冷会话 / 暖场 / gaia 槽位 对 v_voucher 命中率的影响。

固定请求间隔（用 client 自身的 min_delay），只改一个自变量：
  阶段 1  冷会话（账号 cookie 已导入，但没暖场）        —— 现状
  阶段 2  暖场 + 续签 bili_ticket 之后
  阶段 3  再暖场一次 + 带 gaia 指纹槽位
  阶段 4  软风控当场自愈（暖场 + 续签）后再打同一请求

用法：python tests/probe_softrisk_fix.py [--account 1] [--rounds 5]
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


def probe(cli, extra: dict | None = None) -> str:
    """返回 SOFT-RISK / OK / ERROR 判定。"""
    params = dict(BASE)
    if extra:
        params.update(extra)
    try:
        body = cli.request_json(
            C.EP_SEARCH_TYPE, params=params, wbi=True, soft=True, retries=0,
            headers={"Referer": "https://search.bilibili.com/"})
    except Exception as exc:  # noqa: BLE001
        return f"ERROR {type(exc).__name__}: {exc}"
    data = (body or {}).get("data")
    if not isinstance(data, dict):
        return f"ERROR data={type(data).__name__}"
    if "v_voucher" in data:
        return "SOFT-RISK"
    res = data.get("result")
    if isinstance(res, list) and res:
        return f"OK result={len(res)}"
    return f"OK-but-empty keys={sorted(data)[:6]}"


def phase(name: str, cli, rounds: int, extra: dict | None = None) -> dict:
    hits = []
    for i in range(rounds):
        verdict = probe(cli, extra)
        hits.append(verdict)
        print(f"  [{name}] #{i + 1} -> {verdict}", flush=True)
    soft = sum(1 for h in hits if h.startswith("SOFT-RISK"))
    return {"phase": name, "rounds": rounds, "soft_risk": soft,
            "rate": round(soft / max(1, rounds), 2), "verdicts": hits}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", type=int, default=None)
    ap.add_argument("--rounds", type=int, default=5)
    args = ap.parse_args()

    store = Store(ROOT / "data" / "biliwb.db")
    pool = AccountPool(store, data_dir=ROOT / "data")
    aid = args.account or pool.pick()
    print(f"account={aid} alias={(store.get_account(aid) or {}).get('alias')}", flush=True)
    api = pool.api(aid)
    cli = pool.client(aid)

    report: list[dict] = []
    t0 = time.time()

    # 阶段 1：冷会话（client 刚由 AccountPool 造出来，只有 cookie，没有暖场）
    print("--- 阶段1 冷会话（现状）---", flush=True)
    report.append(phase("cold", cli, args.rounds))

    # 阶段 2：暖场 + 续签
    print("--- warmup + gen_ticket ---", flush=True)
    cli.warmup()
    cli.gen_ticket()
    print("--- 阶段2 暖场后 ---", flush=True)
    report.append(phase("warm", cli, args.rounds))

    # 阶段 3：暖场 + gaia 槽位
    cli.warmup()
    cli.gen_ticket()
    cli._wbi_keys = None
    print("--- 阶段3 暖场 + gaia 槽位 ---", flush=True)
    report.append(phase("warm+gaia", cli, args.rounds, extra=gaia_slots()))

    # 阶段 4：命中软风控时当场自愈（暖场+续签）再重试同一请求
    print("--- 阶段4 命中即自愈重试 ---", flush=True)
    recovered = []
    for i in range(args.rounds):
        v1 = probe(cli)
        if v1 == "SOFT-RISK":
            cli.warmup()
            cli.gen_ticket()
            cli._wbi_keys = None
            v2 = probe(cli)
            recovered.append({"first": v1, "after_recover": v2})
            print(f"  #{i + 1} 软风控 -> 自愈后 {v2}", flush=True)
        else:
            recovered.append({"first": v1, "after_recover": None})
            print(f"  #{i + 1} -> {v1}（未命中，无需自愈）", flush=True)
    healed = sum(1 for r in recovered if r["first"] == "SOFT-RISK"
                 and (r["after_recover"] or "").startswith("OK"))
    attempts = sum(1 for r in recovered if r["first"] == "SOFT-RISK")
    report.append({"phase": "soft-risk self-heal", "attempts": attempts,
                   "healed": healed, "detail": recovered})

    print("\n== 汇总（v_voucher 命中率）==")
    for r in report[:-1]:
        print(f"  {r['phase']:<12} {r['soft_risk']}/{r['rounds']}  rate={r['rate']}")
    print(f"  自愈：命中 {attempts} 次，其中自愈成功 {healed} 次")
    print(f"  耗时 {time.time() - t0:.0f}s, http_calls={cli.http_calls}")

    (OUT / f"softrisk_{int(time.time())}.json").write_text(
        json.dumps({"account": aid, "report": report}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

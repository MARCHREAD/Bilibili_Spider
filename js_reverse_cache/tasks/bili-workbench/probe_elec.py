"""确认"充电人数"的正确字段来源（acc/info.elec vs ugcpay 接口）。"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from biliwb import constants as C  # noqa: E402
from biliwb.client import BiliClient, gaia_slots  # noqa: E402

MIDS = [480959917, 86889715]


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    cli = BiliClient(cookie_file=str(here / "session.txt"), min_delay=1.3, retries=2)
    cli.bootstrap()
    cli.warmup()
    cli.gen_ticket()
    cli.wbi_keys(refresh=True)

    for mid in MIDS:
        try:
            d = cli.request_json(C.EP_ACC_INFO, params={
                "mid": mid, "token": "", "platform": "web",
                "web_location": 1550101, **gaia_slots()}, wbi=True)
        except Exception as exc:
            print(f"[FAIL] acc/info {mid}: {exc}", file=sys.stderr)
            continue
        print(f"\n=== mid={mid} name={d.get('name')} ===", file=sys.stderr)
        for key in ("elec", "level", "fans_medal", "official", "vip", "is_senior_member", "fans_badge"):
            if key in d:
                print(f"  {key}: {json.dumps(d[key], ensure_ascii=False)[:300]}", file=sys.stderr)
        # 全字段里搜索可能的"充电"线索
        hits = {k: v for k, v in d.items()
                if isinstance(v, (int, str, bool)) and any(
                    s in k.lower() for s in ("elec", "charge", "power", "customer", "pay"))}
        print(f"  充电相关标量字段: {json.dumps(hits, ensure_ascii=False)}", file=sys.stderr)

        for label, url, params in [
            ("ugcpay-space/stat", f"{C.API}/x/ugcpay-space/stat", {"mid": mid}),
            ("ugcpay-rank elec month up", f"{C.API}/x/ugcpay-rank/elec/month/up",
             {"up_mid": mid, "web_location": 333.1387}),
            ("space/wbi/acc/info elec via elec/status", f"{C.API}/x/ugcpay/elec/status", {"mid": mid}),
        ]:
            try:
                data = cli.request_json(url, params=params, retries=1)
                print(f"  [{label}] OK -> {json.dumps(data, ensure_ascii=False)[:200]}", file=sys.stderr)
            except Exception as exc:
                print(f"  [{label}] {type(exc).__name__}: {exc}", file=sys.stderr)

    print(f"\nhttp_calls={cli.http_calls}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

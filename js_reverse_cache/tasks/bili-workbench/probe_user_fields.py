"""诊断 user_profile 里仍为空/报错的字段（区分"需要登录"与"接口选错"）。"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from biliwb import constants as C  # noqa: E402
from biliwb.client import BiliClient, gaia_slots  # noqa: E402

MID = 480959917


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    cli = BiliClient(cookie_file=str(here / "session.txt"), min_delay=1.2, retries=2, verbose=False)
    cli.bootstrap()
    cli.warmup()
    cli.gen_ticket()
    cli.wbi_keys(refresh=True)

    for label, url, params, wbi in [
        ("upstat", C.EP_UPSTAT, {"mid": MID, "web_location": 333.1387}, False),
        ("navnum", C.EP_NAVNUM, {"mid": MID, "web_location": 333.1387}, False),
        ("setting.privacy", C.EP_SETTING, {"mid": MID, "web_location": 333.1387}, False),
        ("elec ugcpay-space/stat", C.EP_ELEC, {"mid": MID, "web_location": 333.1387}, False),
        ("elec ugcpay-rank month", f"{C.API}/x/ugcpay-rank/elec/month/up",
         {"up_mid": MID, "web_location": 333.1387}, False),
        ("acc/info", C.EP_ACC_INFO, {"mid": MID, "token": "", "platform": "web",
                                     "web_location": 1550101, **gaia_slots()}, True),
        ("followings", C.EP_FOLLOWINGS, {"vmid": MID, "pn": 1, "ps": 20,
                                         "order": "desc", "order_type": "attention",
                                         "web_location": 333.1387}, False),
        ("followers", C.EP_FOLLOWERS, {"vmid": MID, "pn": 1, "ps": 20,
                                       "web_location": 333.1387}, False),
        ("dyn space", C.EP_DYN_SPACE, {"host_mid": MID, "web_location": 333.1387}, False),
    ]:
        try:
            data = cli.request_json(url, params=params, wbi=wbi, retries=1)
            keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
            sample = {k: data[k] for k in list(data)[:8]} if isinstance(data, dict) else data
            print(f"[OK]   {label:<24} keys={keys}", file=sys.stderr)
            print(f"       {json.dumps(sample, ensure_ascii=False)[:220]}", file=sys.stderr)
        except Exception as exc:
            print(f"[FAIL] {label:<24} {type(exc).__name__}: {exc}", file=sys.stderr)

    print(f"\nhttp_calls={cli.http_calls}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

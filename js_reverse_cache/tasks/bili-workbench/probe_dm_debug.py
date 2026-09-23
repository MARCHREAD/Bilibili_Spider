"""调试：弹幕 seg.so 的 HTTP 304 来源。"""

from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from biliwb import constants as C  # noqa: E402
from biliwb import wbi as wbi_mod  # noqa: E402
from biliwb.client import BiliClient  # noqa: E402

BV = "BV1v1gGzqEVP"


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    cli = BiliClient(cookie_file=str(here / "session.txt"), min_delay=1.0, retries=0, verbose=True)
    cli.bootstrap()
    cli.warmup()
    cli.wbi_keys(refresh=True)

    view = cli.request_json(C.EP_VIEW, params={"bvid": BV}, wbi=True)
    cid, aid, duration = view["cid"], view["aid"], view["duration"]
    print(f"cid={cid} aid={aid} duration={duration}", file=sys.stderr)

    img, sub = cli.wbi_keys()

    for label, params in [
        ("plain params (no wbi, no ps/pe)", {"type": 1, "oid": cid, "pid": aid,
                                             "segment_index": 1, "pull_mode": 1,
                                             "web_location": 1315873}),
        ("with ps/pe", {"type": 1, "oid": cid, "pid": aid, "segment_index": 1,
                        "pull_mode": 1, "ps": 0, "pe": 120000, "web_location": 1315873}),
        ("segment_index=2", {"type": 1, "oid": cid, "pid": aid, "segment_index": 2,
                             "pull_mode": 1, "ps": 0, "pe": 120000, "web_location": 1315873}),
    ]:
        signed = wbi_mod.sign(params, img, sub)
        resp = cli._raw("GET", C.EP_DM_SEG, params=signed)
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
        interesting = {k: hdrs.get(k) for k in
                       ("content-type", "content-length", "content-encoding", "status",
                        "etag", "last-modified", "cache-control", "x-cache-webcdn",
                        "x-rid-result", "vary", "age")}
        print(f"\n[{label}] status={resp.status_code} len={len(resp.content)}", file=sys.stderr)
        print(f"  headers: {interesting}", file=sys.stderr)
        if resp.status_code == 304:
            print("  -> 304: 需要判断是服务端条件缓存还是参数问题", file=sys.stderr)
        elif resp.status_code == 200 and resp.content:
            print(f"  -> 200, first bytes: {resp.content[:16].hex()}", file=sys.stderr)
        time.sleep(1.2)

    print(f"\nhttp_calls={cli.http_calls}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

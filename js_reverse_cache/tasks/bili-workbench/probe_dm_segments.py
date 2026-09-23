"""澄清弹幕分段协议：DmWebViewReply 结构 + seg.so 的 segment/ps/pe 语义。"""

from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from biliwb import constants as C  # noqa: E402
from biliwb import proto  # noqa: E402
from biliwb import wbi as wbi_mod  # noqa: E402
from biliwb.client import BiliClient  # noqa: E402

BV = "BV1v1gGzqEVP"


def count_elems(raw: bytes) -> int:
    if not raw:
        return 0
    try:
        return len(proto.parse(raw).get(1, []))
    except Exception:
        return -1


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    cli = BiliClient(cookie_file=str(here / "session.txt"), min_delay=0.9, retries=0)
    cli.bootstrap()
    cli.warmup()
    cli.wbi_keys(refresh=True)

    view = cli.request_json(C.EP_VIEW, params={"bvid": BV}, wbi=True)
    cid, aid, duration = view["cid"], view["aid"], view["duration"]
    print(f"bvid={BV} cid={cid} aid={aid} duration={duration}s", file=sys.stderr)

    raw_view = cli.request_bytes(C.EP_DM_VIEW, params={
        "type": 1, "oid": cid, "pid": aid, "duration": duration,
        "without_subtitle": "true", "web_location": 1315873}, wbi=True)
    top = proto.parse(raw_view)
    print(f"\nDmWebViewReply ({len(raw_view)} bytes) 顶层字段:", file=sys.stderr)
    for fno, vals in sorted(top.items()):
        v = vals[0]
        if isinstance(v, dict) and "_msg" in v:
            inner = {k: vv[0] for k, vv in sorted(v["_msg"].items())}
            print(f"  f{fno}: <msg {inner}>", file=sys.stderr)
        else:
            print(f"  f{fno}: {str(v)[:80]}", file=sys.stderr)

    img, sub = cli.wbi_keys()
    base = {"type": 1, "oid": cid, "pid": aid, "pull_mode": 1, "web_location": 1315873}

    print("\n== A. 固定 pe=120000，扫 segment_index ==", file=sys.stderr)
    for idx in range(1, 8):
        params = {**base, "segment_index": idx, "ps": 0, "pe": 120000}
        resp = cli._raw("GET", C.EP_DM_SEG, params=wbi_mod.sign(params, img, sub))
        n = count_elems(resp.content)
        print(f"  seg={idx} status={resp.status_code} bytes={len(resp.content)} elems={n}",
              file=sys.stderr)
        time.sleep(0.8)

    print("\n== B. 固定 seg=1，扫 pe ==", file=sys.stderr)
    for pe in (60000, 120000, 240000, 360000, 600000, 1200000, 1400000):
        params = {**base, "segment_index": 1, "ps": 0, "pe": pe}
        resp = cli._raw("GET", C.EP_DM_SEG, params=wbi_mod.sign(params, img, sub))
        n = count_elems(resp.content)
        print(f"  pe={pe} status={resp.status_code} bytes={len(resp.content)} elems={n}",
              file=sys.stderr)
        time.sleep(0.8)

    print("\n== C. 只带 segment_index（无 ps/pe）==", file=sys.stderr)
    for idx in (1, 2, 3):
        params = {**base, "segment_index": idx}
        resp = cli._raw("GET", C.EP_DM_SEG, params=wbi_mod.sign(params, img, sub))
        n = count_elems(resp.content)
        print(f"  seg={idx} status={resp.status_code} bytes={len(resp.content)} elems={n}",
              file=sys.stderr)
        time.sleep(0.8)

    print(f"\nhttp_calls={cli.http_calls}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

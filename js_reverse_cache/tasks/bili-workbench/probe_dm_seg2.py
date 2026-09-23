"""判定 segment_index>1 的 304 是"段不存在"还是"请求过密限流"。

设计：每次**只发一个** seg 请求，前置 3 秒静默；对比首次请求与重复请求。
"""

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


def probe(cli, img, sub, cid, aid, seg, ps, pe):
    params = {"type": 1, "oid": cid, "pid": aid, "segment_index": seg,
              "pull_mode": 1, "ps": ps, "pe": pe, "web_location": 1315873}
    resp = cli._raw("GET", C.EP_DM_SEG, params=wbi_mod.sign(params, img, sub))
    n = 0
    span = None
    if resp.status_code == 200 and resp.content:
        try:
            elems = proto.parse(resp.content).get(1, [])
            n = len(elems)
            progs = []
            for e in elems:
                m = e.get("_msg") if isinstance(e, dict) else None
                if isinstance(m, dict):
                    p = proto.scalar(m, 2)
                    if isinstance(p, int):
                        progs.append(p)
            if progs:
                span = (min(progs), max(progs))
        except Exception as exc:
            n = f"parse-error {exc}"
    return resp.status_code, len(resp.content), n, span


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    cli = BiliClient(cookie_file=str(here / "session.txt"), min_delay=0.5, retries=0)
    cli.bootstrap()
    cli.warmup()
    cli.wbi_keys(refresh=True)
    view = cli.request_json(C.EP_VIEW, params={"bvid": BV}, wbi=True)
    cid, aid, duration = view["cid"], view["aid"], view["duration"]
    img, sub = cli.wbi_keys()
    print(f"cid={cid} duration={duration}s", file=sys.stderr)

    # 每次只发一个请求，中间静默 3s
    plan = [
        ("seg=2 alone (first ever)", 2, 0, 360000),
        ("seg=2 repeat", 2, 0, 360000),
        ("seg=1", 1, 0, 360000),
        ("seg=3 alone", 3, 0, 360000),
        ("seg=2 relative ps window", 2, 0, 120000),
        ("seg=1 ps=360000", 1, 360000, 360000),
    ]
    for label, seg, ps, pe in plan:
        time.sleep(3.0)
        status, size, n, span = probe(cli, img, sub, cid, aid, seg, ps, pe)
        span_txt = f" span={span[0]}-{span[1]}ms" if span else ""
        print(f"  {label:<32} seg={seg} ps={ps} pe={pe} -> {status} bytes={size} "
              f"elems={n}{span_txt}", file=sys.stderr)

    print(f"\nhttp_calls={cli.http_calls}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

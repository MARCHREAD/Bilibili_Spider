"""确定弹幕全量获取路径：XML 全量接口 vs seg.so 的 (ps,pe) 滑窗。"""

from __future__ import annotations

import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from biliwb import constants as C  # noqa: E402
from biliwb import proto  # noqa: E402
from biliwb import wbi as wbi_mod  # noqa: E402
from biliwb.client import BiliClient  # noqa: E402

BV = "BV1v1gGzqEVP"
XML_EP = f"{C.API}/x/v1/dm/list.so"


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
    print(f"cid={cid} duration={duration}s danmaku_stat={view['stat']['danmaku']}", file=sys.stderr)

    # ---- 路径一：经典 XML 全量接口
    print("\n== A. x/v1/dm/list.so (XML 全量) ==", file=sys.stderr)
    for label, params in [("oid only", {"oid": cid}),
                          ("oid+type", {"oid": cid, "type": 1})]:
        resp = cli._raw("GET", XML_EP, params=params,
                        headers={"Referer": f"{C.WWW}/video/{BV}/"})
        text = getattr(resp, "text", "") or ""
        ds = re.findall(r"<d p=\"([^\"]+)\">", text)
        print(f"  {label}: status={resp.status_code} bytes={len(resp.content)} "
              f"<d> count={len(ds)}", file=sys.stderr)
        if ds:
            print(f"    first p= {ds[0][:70]}", file=sys.stderr)
            print(f"    last  p= {ds[-1][:70]}", file=sys.stderr)
        time.sleep(0.9)

    # ---- 路径二：seg.so 的 (ps,pe) 滑窗
    img, sub = cli.wbi_keys()
    base = {"type": 1, "oid": cid, "pid": aid, "pull_mode": 1,
            "segment_index": 1, "web_location": 1315873}
    print("\n== B. seg.so (ps,pe) 滑窗 ==", file=sys.stderr)
    windows = [(0, 120000), (0, 360000), (120000, 240000), (240000, 360000),
               (360000, 720000), (720000, 1080000), (0, 1343000)]
    for ps, pe in windows:
        params = {**base, "ps": ps, "pe": pe}
        resp = cli._raw("GET", C.EP_DM_SEG, params=wbi_mod.sign(params, img, sub))
        n = count_elems(resp.content)
        print(f"  ps={ps:<8} pe={pe:<8} status={resp.status_code} "
              f"bytes={len(resp.content)} elems={n}", file=sys.stderr)
        time.sleep(0.9)

    print(f"\nhttp_calls={cli.http_calls}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

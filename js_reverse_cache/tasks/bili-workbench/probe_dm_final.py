"""交叉验证弹幕分段语义：DmSegConfig.total 是否等于真实段数。"""

from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from biliwb import constants as C  # noqa: E402
from biliwb import proto  # noqa: E402
from biliwb import wbi as wbi_mod  # noqa: E402
from biliwb.client import BiliClient  # noqa: E402

VIDEOS = ["BV1X9eb6tEvy", "BV1BHez6cEEm", "BV1v1gGzqEVP"]
XML_EP = f"{C.API}/x/v1/dm/list.so"


def seg_config(raw: bytes) -> dict:
    top = proto.parse(raw)
    cfg = proto.scalar(top, 4)
    if isinstance(cfg, dict) and "_msg" in cfg:
        return {"page_size": proto.scalar(cfg["_msg"], 1), "total": proto.scalar(cfg["_msg"], 2)}
    return {}


def progress_span(elems) -> str:
    vals = []
    for e in elems:
        m = e.get("_msg") if isinstance(e, dict) else None
        if isinstance(m, dict):
            p = proto.scalar(m, 2)
            if isinstance(p, int):
                vals.append(p)
    return f"{min(vals)}-{max(vals)}ms (n={len(vals)})" if vals else "n/a"


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    cli = BiliClient(cookie_file=str(here / "session.txt"), min_delay=1.0, retries=0)
    cli.bootstrap()
    cli.warmup()
    cli.wbi_keys(refresh=True)
    img, sub = cli.wbi_keys()

    for bvid in VIDEOS:
        view = cli.request_json(C.EP_VIEW, params={"bvid": bvid}, wbi=True)
        cid, aid, duration = view["cid"], view["aid"], view["duration"]
        stat_dm = (view.get("stat") or {}).get("danmaku")
        expect = max(1, -(-duration // 360))
        raw = cli.request_bytes(C.EP_DM_VIEW, params={
            "type": 1, "oid": cid, "pid": aid, "duration": duration,
            "without_subtitle": "true", "web_location": 1315873}, wbi=True)
        cfg = seg_config(raw)

        print(f"\n{bvid}: duration={duration}s stat.danmaku={stat_dm} "
              f"ceil(dur/360)={expect}", file=sys.stderr)
        print(f"  DmSegConfig={cfg}", file=sys.stderr)

        total = int(cfg.get("total") or 1)
        page = int(cfg.get("page_size") or 360000)
        for seg in range(1, min(total, 5) + 1):
            params = {"type": 1, "oid": cid, "pid": aid, "segment_index": seg,
                      "pull_mode": 1, "ps": 0, "pe": page, "web_location": 1315873}
            resp = cli._raw("GET", C.EP_DM_SEG, params=wbi_mod.sign(params, img, sub))
            elems = proto.parse(resp.content).get(1, []) if resp.status_code == 200 and resp.content else []
            print(f"    seg={seg}: status={resp.status_code} bytes={len(resp.content)} "
                  f"elems={len(elems)} span={progress_span(elems)}", file=sys.stderr)

        xml = cli._raw("GET", XML_EP, params={"oid": cid},
                       headers={"Referer": f"{C.WWW}/video/{bvid}/"})
        ds = re.findall(r'<d p="([^"]+)"', getattr(xml, "text", "") or "")
        spans = [float(x.split(",")[0]) for x in ds] if ds else []
        print(f"    XML list.so: status={xml.status_code} count={len(ds)} "
              f"span={f'{min(spans):.0f}-{max(spans):.0f}s' if spans else 'n/a'}",
              file=sys.stderr)

    print(f"\nhttp_calls={cli.http_calls}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""证明/证伪 midHash 算法（弹幕发送者 uid 还原的前提）。

方法
----
弹幕只给 `midHash`，评论给 `uid`。同一视频里既评论又发弹幕的用户，
其 (uid, midHash) 构成真实配对。

取该视频**全量弹幕 midHash 集合**（XML `x/v1/dm/list.so`，实测对中小弹幕
视频返回全量：286/286、35/35 与 stat.danmaku 完全一致），与评论区 uid 集合
按多个候选算法互算，看哪个候选产生非随机命中。

随机碰撞期望 = |mids| * |hashes| / 2^32，量级 ~1e-3，可忽略。

用法：python probe_midhash.py
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import sys
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from biliwb import constants as C  # noqa: E402
from biliwb.api import comment as comment_mod  # noqa: E402
from biliwb.client import BiliClient  # noqa: E402

SALT = "DU8tF3z6"
XML_EP = f"{C.API}/x/v1/dm/list.so"
TARGET = "BV1v1gGzqEVP"   # 评论 13.8 万 / 弹幕巨大


def c32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


CANDIDATES = {
    "A crc32(str(mid))": lambda m: f"{c32(str(m).encode()):08x}",
    "B crc32(str(crc32(mid))+SALT)": lambda m: f"{c32((str(c32(str(m).encode())) + SALT).encode()):08x}",
    "C crc32(str(mid)+SALT)": lambda m: f"{c32((str(m) + SALT).encode()):08x}",
    "D crc32(SALT+str(mid))": lambda m: f"{c32((SALT + str(m)).encode()):08x}",
    "E md5(str(mid))[:8]": lambda m: hashlib.md5(str(m).encode()).hexdigest()[:8],
    "F crc32(str(crc32(mid)))": lambda m: f"{c32(str(c32(str(m).encode())).encode()):08x}",
}


def fetch_all_midhashes(cli: BiliClient, bvid: str) -> tuple[set[str], dict]:
    view = cli.request_json(C.EP_VIEW, params={"bvid": bvid}, wbi=True)
    cid = view["cid"]
    xml = cli._raw("GET", XML_EP, params={"oid": cid},
                   headers={"Referer": f"{C.WWW}/video/{bvid}/"})
    text = getattr(xml, "text", "") or ""
    rows = re.findall(r'<d p="([^"]+)"', text)
    hashes = set()
    for row in rows:
        parts = row.split(",")
        if len(parts) >= 7 and len(parts[6]) == 8:
            hashes.add(parts[6])
    return hashes, {"cid": cid, "stat_danmaku": (view.get("stat") or {}).get("danmaku"),
                    "xml_rows": len(rows)}


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    cli = BiliClient(cookie_file=str(here / "session.txt"), min_delay=1.0, retries=4)
    cli.bootstrap()
    cli.warmup()
    cli.gen_ticket()
    cli.save_cookies()
    cli.wbi_keys(refresh=True)

    hashes, info = fetch_all_midhashes(cli, TARGET)
    print(f"danmaku: stat={info['stat_danmaku']} xml_rows={info['xml_rows']} "
          f"unique_midHash={len(hashes)}", file=sys.stderr)

    cache: dict = {}
    mids: set[int] = set()
    for page in range(1, 13):
        try:
            data = comment_mod.video_comments(cli, TARGET, cache, page=page,
                                              with_sub=True, sub_pages=2)
        except Exception as exc:
            print(f"  page {page} stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
            break
        before = len(mids)
        for item in data.get("items", []):
            mid = (item.get("member") or {}).get("mid")
            if mid:
                mids.add(int(mid))
            for sub in item.get("sub_comments", []) or []:
                smid = (sub.get("member") or {}).get("mid")
                if smid:
                    mids.add(int(smid))
        print(f"  page {page}: mids {before}->{len(mids)} end={data.get('is_end')}",
              file=sys.stderr)
        if data.get("is_end"):
            break

    expect = len(mids) * len(hashes) / (2 ** 32)
    print(f"\n评论作者 uid: {len(mids)}   弹幕 midHash: {len(hashes)}   "
          f"随机碰撞期望≈{expect:.2e}", file=sys.stderr)

    results = {}
    for name, fn in CANDIDATES.items():
        hits = [m for m in mids if fn(m) in hashes]
        results[name] = hits
        print(f"  {name:<32} 命中 {len(hits)}", file=sys.stderr)
        for m in hits[:3]:
            print(f"      mid={m} -> {fn(m)}", file=sys.stderr)

    best = max(results, key=lambda k: len(results[k]))
    print(f"\n=> 最佳候选: {best} (命中 {len(results[best])})", file=sys.stderr)
    if results[best]:
        print("=> PASS: 该规则被真实配对证实", file=sys.stderr)
        return 0
    print("=> INCONCLUSIVE: 全部候选零命中", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())

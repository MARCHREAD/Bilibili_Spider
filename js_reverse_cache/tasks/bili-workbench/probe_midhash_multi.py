"""不依赖登录的 midHash 算法验证：跨视频汇总候选池 x 弹幕 midHash 池求交。

原理
----
`midHash` 只是 uid 的函数（与视频无关）。所以可以对**多个视频**分别收集：
  * 候选 uid 池：每个视频的 UP 主 mid + 该视频评论区（含二级）作者 mid
  * 弹幕 midHash 池：每个视频的 XML 全量弹幕 midHash

若某 uid 在视频 A 被观测到、而它的 midHash 出现在视频 B 的弹幕里，
这仍然是一条**真实的 (uid, midHash) 配对**，足以证实/证伪算法。

随机碰撞期望 = |pool| * |hashes| / 2^32（量级 1e-3 ~ 1e-2），可忽略。

用法：python probe_midhash_multi.py [视频数，默认 15]
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
KEYWORD = "原神"


def c32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


CANDIDATES = {
    "A crc32(str(mid))": lambda m: f"{c32(str(m).encode()):08x}",
    "B crc32(str(crc32(mid))+SALT)": lambda m: f"{c32((str(c32(str(m).encode())) + SALT).encode()):08x}",
    "C crc32(str(mid)+SALT)": lambda m: f"{c32((str(m) + SALT).encode()):08x}",
    "D crc32(SALT+str(mid))": lambda m: f"{c32((SALT + str(m)).encode()):08x}",
    "E crc32(str(crc32(mid)))": lambda m: f"{c32(str(c32(str(m).encode())).encode()):08x}",
    "F md5(str(mid))[:8]": lambda m: hashlib.md5(str(m).encode()).hexdigest()[:8],
    "G crc32(mid bytes int)": lambda m: f"{c32(int(m).to_bytes(8, 'big')):08x}",
}


def main() -> int:
    want = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    here = pathlib.Path(__file__).resolve().parent
    cli = BiliClient(cookie_file=str(here / "session.txt"), min_delay=1.0, jitter=0.3, retries=4)
    cli.bootstrap()
    cli.warmup()
    cli.gen_ticket()
    cli.save_cookies()
    cli.wbi_keys(refresh=True)

    data = cli.request_json(C.EP_SEARCH_TYPE, params={
        "search_type": "video", "keyword": KEYWORD, "order": "dm", "page": 1,
        "page_size": 30, "duration": 0, "from_source": "", "web_location": 1430654,
    }, wbi=True, headers={"Referer": "https://search.bilibili.com/"})
    bvids = [it.get("bvid") for it in (data or {}).get("result") or [] if it.get("bvid")][:want]
    print(f"样本视频: {len(bvids)}", file=sys.stderr)

    pool: set[int] = set()
    hashes: set[str] = set()
    cache: dict = {}
    per_video = []

    for bvid in bvids:
        try:
            view = cli.request_json(C.EP_VIEW, params={"bvid": bvid}, wbi=True)
        except Exception as exc:
            print(f"  {bvid} view 失败: {exc}", file=sys.stderr)
            continue
        owner = (view.get("owner") or {}).get("mid")
        cid = view.get("cid")

        xml = cli._raw("GET", XML_EP, params={"oid": cid},
                       headers={"Referer": f"{C.WWW}/video/{bvid}/"})
        rows = re.findall(r'<d p="([^"]+)"', getattr(xml, "text", "") or "")
        v_hashes = {r.split(",")[6] for r in rows if len(r.split(",")) >= 7}
        hashes |= v_hashes

        mids: set[int] = set()
        if owner:
            mids.add(int(owner))
        try:
            cdata = comment_mod.video_comments(cli, bvid, cache, page=1,
                                               with_sub=True, sub_pages=1)
            for item in cdata.get("items", []):
                mid = (item.get("member") or {}).get("mid")
                if mid:
                    mids.add(int(mid))
                for sub in item.get("sub_comments", []) or []:
                    smid = (sub.get("member") or {}).get("mid")
                    if smid:
                        mids.add(int(smid))
        except Exception as exc:
            print(f"  {bvid} 评论失败: {exc}", file=sys.stderr)
        pool |= mids
        per_video.append((bvid, len(v_hashes), len(mids)))
        print(f"  {bvid}: 弹幕hash={len(v_hashes)} 候选uid={len(mids)}", file=sys.stderr)

    expect = len(pool) * len(hashes) / (2 ** 32)
    print(f"\n合计: 候选 uid={len(pool)}  弹幕 midHash={len(hashes)}  "
          f"随机碰撞期望≈{expect:.2e}", file=sys.stderr)

    results = {}
    for name, fn in CANDIDATES.items():
        hits = [m for m in pool if fn(m) in hashes]
        results[name] = hits
        print(f"  {name:<30} 命中 {len(hits)}", file=sys.stderr)
        for m in hits[:4]:
            print(f"      mid={m} -> {fn(m)}", file=sys.stderr)

    best = max(results, key=lambda k: len(results[k]))
    n = len(results[best])
    print(f"\n=> 最佳候选: {best} (命中 {n})", file=sys.stderr)

    import json as _json
    fixture = here / "fixtures" / "midhash_pairs.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(_json.dumps({
        "kind": "midhash-uid-pairs",
        "scheme": "midHash = 8-char lowercase hex of crc32(str(uid))",
        "how": ("multi-video intersection: candidate uid pool (video owners + comment "
                "authors incl. sub-comments) x danmaku midHash pool from XML list.so"),
        "note": "uid and midHash are public danmaku metadata; no cookies or tokens here.",
        "random_collision_expectation": expect,
        "pool_size": len(pool),
        "hash_pool_size": len(hashes),
        "candidates_tested": list(CANDIDATES),
        "hits_per_candidate": {k: len(v) for k, v in results.items()},
        "pairs": [{"uid": m, "mid_hash": CANDIDATES[best](m)} for m in results[best]],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"=> 固定向量已保存: {fixture}", file=sys.stderr)

    if n > 0:
        print("=> PASS: 该规则被真实 (uid, midHash) 配对证实", file=sys.stderr)
        also = [k for k, v in results.items() if v and k != best]
        print(f"=> 其他候选命中: {also or '无'}（应全为 0，否则规则不唯一）", file=sys.stderr)
        return 0
    print("=> INCONCLUSIVE: 全部候选零命中，需登录后扩大候选池", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())

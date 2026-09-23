"""端到端接受性探针（live，只读 GET）。

目的：
  1. 确认纯 Python + curl_cffi 会话能否通过 bilibili 风控（HTTP 412 / code -352）；
  2. 固化每个业务接口的真实参数集与响应结构；
  3. 判定弹幕 protobuf 里到底有哪些字段（决定 2.4 的实现形态）。

stdout = 机器可读 JSON；stderr = 人类可读摘要。
用法：python probe_endpoints.py
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from biliwb import constants as C  # noqa: E402
from biliwb.client import BiliClient  # noqa: E402

BV = "BV1BHez6cEEm"
AID = 117303375104693
CID = 42057075469
MID = 86889715
KEYWORD = "原神"


def brief(obj, depth: int = 0, max_items: int = 6):
    """把响应裁成可读轮廓。"""
    if isinstance(obj, dict):
        return {k: brief(v, depth + 1, max_items) for k, v in list(obj.items())[:14]} if depth < 2 else f"<dict {len(obj)} keys>"
    if isinstance(obj, list):
        head = [brief(v, depth + 1, max_items) for v in obj[:2]]
        return head if depth < 2 else f"<list {len(obj)}>"
    if isinstance(obj, str) and len(obj) > 60:
        return obj[:60] + "..."
    return obj


def main() -> int:
    cli = BiliClient(cookie_file=str(pathlib.Path(__file__).resolve().parent / "session.txt"), verbose=True)
    report: dict = {"impersonate": cli.impersonate, "results": {}}

    print("== bootstrap ==", file=sys.stderr)
    cli.bootstrap()
    cli.gen_ticket()
    nav = cli.nav(refresh=True)
    report["login"] = {"isLogin": nav.get("isLogin"), "mid": nav.get("mid"), "uname": nav.get("uname")}
    print(f"nav: isLogin={nav.get('isLogin')} mid={nav.get('mid')} wbi={cli._wbi_keys is not None}", file=sys.stderr)

    tests = [
        ("2.2 view", C.EP_VIEW, {"bvid": BV}, True, False),
        ("2.1 search", C.EP_SEARCH_TYPE, {
            "search_type": "video", "keyword": KEYWORD, "order": "totalrank", "page": 1,
            "page_size": 30, "duration": 0, "from_source": "", "web_location": 1430654,
        }, True, False),
        ("2.3 reply", C.EP_REPLY_MAIN, {
            "oid": AID, "type": 1, "mode": 3, "pagination_str": '{"offset":""}', "plat": 1,
            "seek_rpid": "", "web_location": 1315875,
        }, True, False),
        ("2.2 player_v2", C.EP_PLAYER_V2, {
            "aid": AID, "cid": CID, "isGaiaAvoided": "false", "web_location": 1315873,
            "dm_img_list": "[]", "dm_img_str": C.GAIA_DM_IMG_STR,
            "dm_cover_img_str": C.GAIA_DM_COVER_IMG_STR, "dm_img_inter": C.GAIA_DM_IMG_INTER,
        }, True, False),
        ("2.2 subtitle", C.EP_SUBTITLE_WEB, {
            "oid": CID, "pid": AID, "context_ext": '{"video_type":1}', "type": 1,
            "cur_production_type": 0, "playlist_switch": 0, "web_location": 1315873,
        }, True, False),
        ("2.2 tags", C.EP_TAGS, {"bvid": BV}, False, False),
        ("2.5 acc_info", C.EP_ACC_INFO, {"mid": MID, "token": "", "platform": "web", "web_location": 1550101}, True, False),
        ("2.5 relation_stat", C.EP_RELATION_STAT, {"vmid": MID, "web_location": 333.1387}, False, False),
        ("2.5 upstat", C.EP_UPSTAT, {"mid": MID, "web_location": 333.1387}, False, False),
        ("2.5 navnum", C.EP_NAVNUM, {"mid": MID, "web_location": 333.1387}, False, False),
        ("2.5 setting", C.EP_SETTING, {"mid": MID, "web_location": 333.1387}, False, False),
        ("2.6 arc_search", C.EP_ARC_SEARCH, {
            "pn": 1, "ps": 30, "tid": 0, "special_type": "", "order": "pubdate", "mid": MID,
            "index": 0, "keyword": "", "order_avoided": "true", "platform": "web", "web_location": 333.1387,
        }, True, False),
        ("2.8 dyn_space", C.EP_DYN_SPACE, {"host_mid": MID}, False, False),
        ("2.7 playurl", C.EP_PLAYURL, {
            "avid": AID, "bvid": BV, "cid": CID, "qn": 80, "fnver": 0, "fnval": 4048,
            "fourk": 1, "from_client": "BROWSER", "is_main_page": "true", "need_fragment": "false",
        }, True, False),
    ]

    for label, url, params, use_wbi, need_login in tests:
        entry: dict = {"url": url}
        try:
            data = cli.request_json(url, params=params, wbi=use_wbi, need_login=need_login)
            entry["ok"] = True
            entry["shape"] = brief(data)
            if isinstance(data, dict):
                entry["keys"] = list(data.keys())[:30]
            print(f"[OK]   {label}", file=sys.stderr)
        except Exception as exc:
            entry["ok"] = False
            entry["error"] = f"{type(exc).__name__}: {exc}"
            print(f"[FAIL] {label} -> {entry['error']}", file=sys.stderr)
        report["results"][label] = entry

    # 弹幕 protobuf：单独取字节
    print("== danmaku protobuf ==", file=sys.stderr)
    try:
        raw = cli.request_bytes(C.EP_DM_SEG, params={
            "type": 1, "oid": CID, "pid": AID, "segment_index": 1, "pull_mode": 1,
            "ps": 0, "pe": 120000, "web_location": 1315873,
        }, wbi=True)
        report["danmaku"] = {"bytes": len(raw), "head_hex": raw[:48].hex()}
        pathlib.Path(pathlib.Path(__file__).resolve().parent / "fixtures" / "dm_seg_sample.bin").write_bytes(raw)
        print(f"[OK]   dm seg.so -> {len(raw)} bytes (saved to fixtures/dm_seg_sample.bin)", file=sys.stderr)
    except Exception as exc:
        report["danmaku"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(f"[FAIL] dm seg.so -> {exc}", file=sys.stderr)

    report["http_calls"] = cli.http_calls
    print(f"\nhttp_calls={cli.http_calls}", file=sys.stderr)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""2.4 视频弹幕：protobuf 分段 + XML 全量互补，含发送者身份还原。

协议事实（live 取证 + 本地解码，见 fixtures/dm_seg_sample.bin）
--------------------------------------------------------------
1) `x/v2/dm/wbi/web/seg.so` 返回 `application/octet-stream` 的 protobuf
   （`DmSegMobileReply`），**不是加密**。每个 `DanmakuElem` 字段实测为：

       f1 id | f2 progress(视频内毫秒) | f3 mode | f4 fontsize | f5 color
       f6 midHash | f7 content | f8 ctime(发送时间戳) | f9 weight | f12 idStr | f13 attr

   分段规则（实测）：`dm/web/view` 的 `DmSegConfig = {page_size:360000ms, total:N}`
   才是权威段数；`segment_index` 从 1 开始；不存在的段返回 404（不是空数组）。
   段内可用 `ps`/`pe` 毫秒窗口，且 `pe` 不得超过 `page_size`。

2) `x/v1/dm/list.so` 返回 XML 全量弹幕，`p` 属性为
   `progress(秒),mode,fontsize,color,ctime,pool,midHash,rowID,weight`。
   实测对中小弹幕视频与 `stat.danmaku` **完全一致**（286/286、35/35），
   比 seg.so 更全（同一视频 seg.so 只给 103/12 条），单次上限约 1200 条。

因此默认**两条路径都取并合并去重**（XML 提供覆盖面，protobuf 提供 idStr/attr）。

身份还原
--------
协议**不下发** uid / 昵称 / 等级，只有 `midHash`。本模块提供三级还原，
命中才回填，未命中保持 None 并计入 unresolved，绝不猜测。算法正确性由
`tests/test_midhash.py` 用真实"评论者 uid × 弹幕 midHash"配对证明。
"""

from __future__ import annotations

import html
import math
import re
import zlib
from typing import Any

from .. import constants as C
from .. import proto
from ..client import BiliClient, gaia_slots
from ..errors import TransportError
from ..utils import av2bv, ms_to_clock, normalize_mid, ts_to_str

SEG_PS = 0
DEFAULT_SEGMENT_MS = 360000      # DmSegConfig.page_size 的实测值（6 分钟）
SEG_FALLBACK_SECONDS = 360
XML_EP = f"{C.API}/x/v1/dm/list.so"

COLOR_NAMES = {16777215: "白色", 16711680: "红色", 16776960: "黄色",
               65280: "绿色", 255: "蓝色", 16711935: "粉色"}


def mid_hash_of(mid: int) -> str:
    """uid -> 弹幕 midHash。

    规则经多视频交叉验证证实（见 tests/test_midhash.py 与
    js_reverse_cache/tasks/bili-workbench/probe_midhash_multi.py）：

        midHash = crc32(str(uid)) 的 8 位小写 hex

    实测：候选池 563 个 uid × 20948 个 midHash，本规则命中 19 个真实配对，
    随机碰撞期望仅 2.75e-03；另外 6 个候选（含双重 CRC32 加盐）全部 0 命中。
    """
    return f"{zlib.crc32(str(mid).encode()) & 0xFFFFFFFF:08x}"


# ---------------------------------------------------------------- 解码

def _elem_to_dict(msg: dict) -> dict[str, Any]:
    color = proto.scalar(msg, 5, 16777215) or 0
    progress = proto.scalar(msg, 2, 0) or 0
    ctime = proto.scalar(msg, 8, 0) or 0
    return {
        "id": proto.scalar(msg, 1),
        "id_str": proto.scalar(msg, 12),
        "content": proto.scalar(msg, 7, ""),
        "progress_ms": progress,
        "video_time": ms_to_clock(progress),
        "mode": proto.scalar(msg, 3),
        "fontsize": proto.scalar(msg, 4),
        "color": color,
        "color_hex": f"#{int(color):06X}",
        "send_time": ctime,
        "send_time_str": ts_to_str(ctime),
        "weight": proto.scalar(msg, 9),
        "mid_hash": proto.scalar(msg, 6, ""),
        "uid": None,
        "uname": None,
        "level": None,
        "source": "seg",
    }


def fetch_xml(client: BiliClient, cid: int, bvid: str) -> list[dict]:
    """XML 全量弹幕（中小视频与 stat.danmaku 一致；超大视频截断在约 1200 条）。"""
    resp = client._raw("GET", XML_EP, params={"oid": cid},
                       headers={"Referer": f"{C.WWW}/video/{bvid}/"})
    if resp.status_code != 200:
        return []
    text = getattr(resp, "text", "") or ""
    out: list[dict] = []
    for match in re.finditer(r'<d p="([^"]+)"\s*>(.*?)</d>', text, re.S):
        parts = match.group(1).split(",")
        if len(parts) < 7:
            continue
        try:
            progress_ms = int(float(parts[0]) * 1000)
            mode = int(parts[1])
            fontsize = int(parts[2])
            color = int(parts[3])
            ctime = int(parts[4])
        except ValueError:
            continue
        out.append({
            "id": None,
            "id_str": parts[7] if len(parts) > 7 and parts[7] else None,
            "content": html.unescape(match.group(2)),
            "progress_ms": progress_ms,
            "video_time": ms_to_clock(progress_ms),
            "mode": mode,
            "fontsize": fontsize,
            "color": color,
            "color_hex": f"#{color:06X}",
            "send_time": ctime,
            "send_time_str": ts_to_str(ctime),
            "weight": int(parts[8]) if len(parts) > 8 and parts[8].isdigit() else None,
            "mid_hash": parts[6],
            "uid": None,
            "uname": None,
            "level": None,
            "source": "xml",
        })
    return out


def seg_config(client: BiliClient, cid: int, aid: int, duration: int = 0) -> dict:
    """解析 dm/web/view 的 DmSegConfig（权威分段信息）。"""
    try:
        raw = client.request_bytes(C.EP_DM_VIEW, params={
            "type": 1, "oid": cid, "pid": aid, "duration": duration,
            "without_subtitle": "true", "web_location": 1315873,
        }, wbi=True)
        top = proto.parse(raw)
        cfg = proto.scalar(top, 4)
        if isinstance(cfg, dict) and "_msg" in cfg:
            return {"page_size": proto.scalar(cfg["_msg"], 1) or DEFAULT_SEGMENT_MS,
                    "total": proto.scalar(cfg["_msg"], 2) or 0}
    except Exception:
        pass
    total = max(1, math.ceil(duration / SEG_FALLBACK_SECONDS)) if duration else 0
    return {"page_size": DEFAULT_SEGMENT_MS, "total": total, "source": "computed"}


def fetch_segment(client: BiliClient, cid: int, aid: int, index: int,
                  page_size: int = DEFAULT_SEGMENT_MS) -> list[dict]:
    """取一个 protobuf 分段。不存在的段返回 404 -> 视为空段，不报错。"""
    try:
        raw = client.request_bytes(C.EP_DM_SEG, params={
            "type": 1, "oid": cid, "pid": aid, "segment_index": index,
            "pull_mode": 1, "ps": SEG_PS, "pe": page_size, "web_location": 1315873,
        }, wbi=True, retries=1)
    except TransportError as exc:
        if exc.code == 404:
            return []
        raise
    if not raw:
        return []
    top = proto.parse(raw)
    return [_elem_to_dict(item["_msg"]) for item in top.get(1, [])
            if isinstance(item, dict) and isinstance(item.get("_msg"), dict)]


def _merge(*groups: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for group in groups:
        for item in group:
            key = item.get("id_str") or (f"{item.get('progress_ms')}|"
                                         f"{item.get('content')}|{item.get('mid_hash')}")
            current = merged.get(key)
            if current is None:
                merged[key] = dict(item)
                continue
            for field, value in item.items():
                if value not in (None, "") and current.get(field) in (None, ""):
                    current[field] = value
    out = list(merged.values())
    out.sort(key=lambda x: (x.get("progress_ms") or 0, str(x.get("id_str") or "")))
    return out


# ---------------------------------------------------------------- 主入口

def video_danmaku(
    client: BiliClient,
    ref: str,
    segment_index: int = 0,
    all_segments: bool = False,
    max_segments: int = 40,
    resolve_senders: bool = False,
    candidate_mids: list[int] | None = None,
    enrich_limit: int = 0,
    pool_pages: int = 5,
) -> dict[str, Any]:
    from ..utils import parse_video_ref
    from .paging import clamp_pages

    # 候选池页数同样受"页数 ≤250"的统一上限约束
    pool_pages = clamp_pages(pool_pages, default=5)

    parsed = parse_video_ref(ref)
    bvid = parsed.get("bvid")
    if not bvid:
        raise ValueError("弹幕需要 BV 号或视频链接")

    view = client.request_json(C.EP_VIEW, params={"bvid": bvid}, wbi=True)
    aid = view.get("aid")
    cid = view.get("cid")
    duration = view.get("duration") or 0
    stat_danmaku = (view.get("stat") or {}).get("danmaku")

    cfg = seg_config(client, cid, aid, duration)
    total = int(cfg.get("total") or 0)
    page_size = int(cfg.get("page_size") or DEFAULT_SEGMENT_MS)

    if all_segments or segment_index <= 0:
        indexes = list(range(1, min(max(total, 1), max_segments) + 1))
    else:
        indexes = [int(segment_index)]

    seg_items: list[dict] = []
    fetched: list[int] = []
    for idx in indexes:
        batch = fetch_segment(client, cid, aid, idx, page_size)
        fetched.append(idx)
        for item in batch:
            item["segment_index"] = idx
        seg_items.extend(batch)

    xml_items = fetch_xml(client, cid, bvid) if (all_segments or segment_index <= 0) else []
    items = _merge(xml_items, seg_items)

    coverage = {
        "stat_danmaku": stat_danmaku,
        "xml_count": len(xml_items),
        "seg_count": len(seg_items),
        "merged_count": len(items),
        "complete": bool(stat_danmaku and len(items) >= int(stat_danmaku)),
    }

    identity: dict[str, Any] = {
        "supported": False,
        "resolved": 0,
        "unresolved": len(items),
        "candidate_pool": 0,
        "scheme": "midHash -> uid 需要候选 uid 池碰撞（协议不下发 uid/昵称/等级）",
    }

    if resolve_senders:
        index = getattr(client, "midhash_index", None)
        hashes = {it.get("mid_hash") for it in items if it.get("mid_hash")}

        # 第 1 层：持久化 midHash 字典（跨视频复用，越用命中越多）
        indexed: dict[str, dict] = {}
        if index is not None and hashes:
            try:
                indexed = index.lookup(hashes) or {}
            except Exception as exc:
                print(f"!!! midHash 索引查询失败: {type(exc).__name__}: {exc}",
                      file=__import__("sys").stderr)
        resolved = 0
        for item in items:
            hit = indexed.get(item.get("mid_hash") or "")
            if hit:
                item["uid"] = hit.get("uid")
                item["uname"] = hit.get("uname")
                item["level"] = hit.get("level")
                item["identity_source"] = "index"
                resolved += 1

        # 第 2 层：本次候选池碰撞
        pool = [int(m) for m in (candidate_mids or [])]
        pool_source = "provided" if pool else "none"
        if not pool:
            up_mid = normalize_mid((view.get("owner") or {}).get("mid"))
            pool, pool_source = _pool_from_comments(
                client, aid, pages=pool_pages,
                extra_mids=[up_mid] if up_mid else None)
        table: dict[str, int] = {}
        for mid in pool:
            try:
                table.setdefault(mid_hash_of(mid), mid)
            except Exception:
                continue
        newly: list[dict] = []
        for item in items:
            if item.get("uid"):
                continue
            mid = table.get(item.get("mid_hash") or "")
            if mid is not None:
                item["uid"] = mid
                item["identity_source"] = "pool"
                resolved += 1
                newly.append({"mid_hash": item.get("mid_hash"), "uid": mid,
                              "source": pool_source})
        if index is not None and newly:
            try:
                index.remember(newly)
            except Exception as exc:
                print(f"!!! midHash 索引写入失败: {type(exc).__name__}: {exc}",
                      file=__import__("sys").stderr)

        identity.update({
            "supported": bool(table) or bool(indexed),
            "candidate_pool": len(pool),
            "pool_source": pool_source,
            "index_hits": sum(1 for it in items if it.get("identity_source") == "index"),
            "pool_hits": sum(1 for it in items if it.get("identity_source") == "pool"),
            "resolved": resolved,
            "unresolved": len(items) - resolved,
        })

        if enrich_limit > 0:
            enriched = enrich_profiles(client, items, enrich_limit)
            identity["enriched"] = enriched
            # 拿到 uname/level 后回写字典，下次任何视频都能直接用
            if index is not None:
                backfill = []
                for uid, prof in (enriched.get("profiles") or {}).items():
                    if not isinstance(prof, dict) or "error" in prof:
                        continue
                    for item in items:
                        if item.get("uid") == uid and item.get("mid_hash"):
                            backfill.append({
                                "mid_hash": item["mid_hash"], "uid": uid,
                                "uname": prof.get("uname"), "level": prof.get("level"),
                                "source": "acc_info",
                            })
                            break
                if backfill:
                    try:
                        index.remember(backfill)
                    except Exception as exc:
                        print(f"!!! midHash 索引回写失败: {type(exc).__name__}: {exc}",
                              file=__import__("sys").stderr)

    return {
        "bvid": bvid,
        "aid": aid,
        "cid": cid,
        "duration": duration,
        "segment_total": total,
        "segment_page_size_ms": page_size,
        "segments_fetched": fetched,
        "count": len(items),
        "items": items,
        "coverage": coverage,
        "identity": identity,
        "limitation": (
            "B 站弹幕协议不下发发送者 uid/昵称/等级，只有 midHash。"
            "uid 只能通过候选池碰撞还原（命中率取决于候选池是否包含该用户）；"
            "昵称与等级需再调 acc/info（有请求成本与风控成本）。"
        ),
    }


def _pool_from_comments(client: BiliClient, aid: int, pages: int = 5,
                        extra_mids: list[int] | None = None) -> tuple[list[int], str]:
    """用评论区作者 uid 构建候选池（弹幕发送者常常也评论过）。

    注意：必须把 aid 转成 bvid 再交给 comment 模块 —— 传纯数字串会让
    `parse_video_ref` 直接抛错，池子静默变成空（此前的真实缺陷）。
    UP 主本人的 uid 也一并入池（UP 主常在自己的视频发弹幕）。
    """
    from . import comment as comment_mod

    mids: set[int] = set()
    for mid in (extra_mids or []):
        norm = normalize_mid(mid)
        if norm:
            mids.add(norm)

    cache: dict = {}
    bvid = av2bv(int(aid))
    for page in range(1, pages + 1):
        try:
            data = comment_mod.video_comments(client, bvid, cache, page=page,
                                              with_sub=True, sub_pages=1)
        except Exception as exc:
            print(f"[danmaku] 候选池第 {page} 页评论失败: {type(exc).__name__}: {exc}",
                  file=__import__("sys").stderr)
            break
        for item in data.get("items", []):
            norm = normalize_mid((item.get("member") or {}).get("mid"))
            if norm:
                mids.add(norm)
            for sub in item.get("sub_comments", []) or []:
                sub_mid = normalize_mid((sub.get("member") or {}).get("mid"))
                if sub_mid:
                    mids.add(sub_mid)
        # 置顶评论作者也算候选
        for key in ("top", "upper_top"):
            pinned = data.get(key) or {}
            norm = normalize_mid(pinned.get("mid"))
            if norm:
                mids.add(norm)
        if data.get("is_end"):
            break
    return sorted(mids), "comments+up" if extra_mids else "comments"


def enrich_profiles(client: BiliClient, items: list[dict], limit: int) -> dict:
    """对已命中 uid 的弹幕补昵称/等级（每 uid 一次请求，受 limit 约束）。"""
    targets: list[int] = []
    for item in items:
        uid = item.get("uid")
        if uid and uid not in targets:
            targets.append(uid)
        if len(targets) >= limit:
            break
    profiles: dict[int, dict] = {}
    for uid in targets:
        try:
            data = client.request_json(
                C.EP_ACC_INFO,
                params={"mid": uid, "token": "", "platform": "web",
                        "web_location": 1550101, **gaia_slots()},
                wbi=True, retries=1,
            )
            profiles[uid] = {
                "uname": (data or {}).get("name"),
                "level": ((data or {}).get("level") or 0) or None,
                "sign": (data or {}).get("sign"),
                "face": (data or {}).get("face"),
            }
        except Exception as exc:
            profiles[uid] = {"error": f"{type(exc).__name__}: {exc}"}
    for item in items:
        profile = profiles.get(item.get("uid"))
        if profile and "error" not in profile:
            item["uname"] = profile.get("uname")
            item["level"] = profile.get("level")
    return {"requested": len(targets), "profiles": profiles}

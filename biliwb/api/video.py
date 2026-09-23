"""2.2 视频详情（含字幕/tag/投流判定）与 2.7 视频流。"""

from __future__ import annotations

import json
import re
from typing import Any

from .. import ad as ad_mod
from .. import constants as C
from ..client import BiliClient, gaia_slots
from ..utils import parse_duration, strip_html, ts_to_str
from . import comment as comment_mod

QUALITY_LABEL = {
    127: "8K 超高清", 126: "杜比视界", 125: "HDR 真彩", 120: "4K 超清",
    116: "1080P60 高帧率", 112: "1080P+ 高码率", 80: "1080P 高清",
    74: "720P60 高帧率", 64: "720P 高清", 32: "480P 清晰", 16: "360P 流畅",
    6: "240P 极速",
}

_INIT_RE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;?\s*</script>", re.S)


def video_detail(
    client: BiliClient,
    ref: str,
    with_subtitle: bool = True,
    with_subtitle_text: bool = False,
    with_tags: bool = True,
    with_pinned_comment: bool = True,
    with_page_probe: bool = False,
) -> dict[str, Any]:
    from ..utils import parse_video_ref

    parsed = parse_video_ref(ref)
    bvid = parsed.get("bvid")
    if not bvid:
        raise ValueError("视频详情需要 BV 号或视频链接（短链请先展开）")

    view = client.request_json(C.EP_VIEW, params={"bvid": bvid}, wbi=True)
    aid = view.get("aid")
    cid = view.get("cid")
    owner = view.get("owner") or {}
    stat = view.get("stat") or {}

    result: dict[str, Any] = {
        "bvid": view.get("bvid"),
        "aid": aid,
        "cid": cid,
        "title": view.get("title"),
        "desc": view.get("desc"),
        "pubdate": view.get("pubdate"),
        "pubdate_str": ts_to_str(view.get("pubdate")),
        "duration": view.get("duration"),
        "duration_str": f"{view.get('duration', 0) // 60:02d}:{view.get('duration', 0) % 60:02d}",
        "tname": view.get("tname"),
        "pic": view.get("pic"),
        "videos": view.get("videos"),
        "pages": [
            {"cid": p.get("cid"), "page": p.get("page"), "part": p.get("part"),
             "duration": p.get("duration")}
            for p in (view.get("pages") or [])
        ],
        "author": {
            "mid": owner.get("mid"),
            "name": owner.get("name"),
            "face": owner.get("face"),
        },
        "stat": {
            "view": stat.get("view"),
            "danmaku": stat.get("danmaku"),
            "reply": stat.get("reply"),
            "favorite": stat.get("favorite"),
            "coin": stat.get("coin"),
            "share": stat.get("share"),
            "like": stat.get("like"),
            "now_rank": stat.get("now_rank"),
            "his_rank": stat.get("his_rank"),
        },
        "copyright": view.get("copyright"),
        "dynamic": view.get("dynamic"),
    }

    if with_tags:
        result["tags"] = fetch_tags(client, bvid)

    subtitle_info: dict[str, Any] = {"subtitles": [], "source": None}
    if with_subtitle:
        subtitle_info = fetch_subtitles(client, aid, cid, with_text=with_subtitle_text)
    result["subtitle"] = subtitle_info

    top_comment: dict | None = None
    if with_pinned_comment:
        top_comment = comment_mod.fetch_pinned_comment(client, aid)
    result["pinned_comment"] = top_comment

    page_flags: dict[str, Any] = {}
    if with_page_probe:
        page_flags = probe_video_page(client, bvid)
    result["page_probe"] = page_flags

    traffic = ad_mod.judge_traffic(parsed.get("ad", {}).get("raw_url", ""),
                                   page_flags.get("page_ad_state"))
    promo = ad_mod.judge_promo(top_comment, owner.get("mid"))
    result["traffic"] = traffic
    result["promo"] = promo
    result["ad_verdict"] = ad_mod.combine(traffic, promo)
    return result


def fetch_tags(client: BiliClient, bvid: str) -> list[dict]:
    try:
        data = client.request_json(C.EP_TAGS, params={"bvid": bvid}, retries=1)
    except Exception:
        return []
    return [
        {"tag_id": t.get("tag_id"), "tag_name": t.get("tag_name"),
         "cover": t.get("cover"), "likes": t.get("likes")}
        for t in (data or [])
    ]


def fetch_subtitles(client: BiliClient, aid: int, cid: int,
                    with_text: bool = False) -> dict[str, Any]:
    """字幕需要登录态；未登录时 player/wbi/v2 返回 need_login_subtitle=true 且列表为空。"""
    subs: list[dict] = []
    source = None

    try:
        data = client.request_json(
            C.EP_PLAYER_V2,
            params={"aid": aid, "cid": cid, "isGaiaAvoided": "false",
                    "web_location": 1315873, **gaia_slots()},
            wbi=True, retries=1,
        )
        subs = ((data or {}).get("subtitle") or {}).get("subtitles") or []
        source = "player/wbi/v2"
        need_login = (data or {}).get("need_login_subtitle")
    except Exception as exc:
        need_login = None
        source = f"player/wbi/v2 失败: {exc}"

    if not subs:
        try:
            data = client.request_json(
                C.EP_SUBTITLE_WEB,
                params={"oid": cid, "pid": aid, "context_ext": '{"video_type":1}',
                        "type": 1, "cur_production_type": 0, "playlist_switch": 0,
                        "web_location": 1315873},
                wbi=True, retries=1,
            )
            alt = (data or {}).get("subtitles") or (data or {}).get("subtitle") or []
            if alt:
                subs = alt
                source = "subtitle/web/view"
        except Exception as exc:
            if source is None:
                source = f"subtitle/web/view 失败: {exc}"

    out: list[dict] = []
    for sub in subs:
        url = sub.get("subtitle_url") or ""
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = C.API + url
        item = {
            "lan": sub.get("lan"),
            "lan_doc": sub.get("lan_doc"),
            "ai_status": sub.get("ai_status"),
            "ai_type": sub.get("type"),
            "subtitle_url": url,
        }
        if with_text and url:
            item["body"] = fetch_subtitle_body(client, url)
        out.append(item)

    return {
        "source": source,
        "need_login": need_login,
        "subtitles": out,
        "hint": None if out else "字幕接口未返回内容：未登录时 B 站不下发字幕，请先登录后重试。",
    }


def fetch_subtitle_body(client: BiliClient, url: str) -> list[dict] | None:
    try:
        text = client.get_text(url)
        data = json.loads(text)
    except Exception:
        return None
    return [
        {"from": b.get("from"), "to": b.get("to"), "content": b.get("content")}
        for b in (data or {}).get("body") or []
    ]


def probe_video_page(client: BiliClient, bvid: str) -> dict[str, Any]:
    """视频页 HTML 取证：__INITIAL_STATE__ 的页面广告位 + 披露标签文本。"""
    html = client.get_text(C.EP_VIDEO_PAGE.format(bvid=bvid),
                           headers={"Referer": C.WWW + "/"})
    out: dict[str, Any] = {"html_bytes": len(html)} 
    state: dict = {}
    m = _INIT_RE.search(html)
    if not m:
        m2 = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", html, re.S)
        m = m2
    if m:
        raw = m.group(1).replace("undefined", "null")
        try:
            state = json.loads(raw)
            out["initial_state_keys"] = list(state.keys())[:40]
        except Exception as exc:
            out["initial_state_error"] = str(exc)
    else:
        out["initial_state_error"] = "未匹配到 __INITIAL_STATE__"
    out["page_ad_state"] = ad_mod.scan_page_ad_state(state)
    out["disclosure"] = ad_mod.scan_html_disclosure(html)
    return out


def video_stream(client: BiliClient, ref: str, qn: int = 80, fnval: int = 4048) -> dict[str, Any]:
    """2.7 取播放流（DASH / FLV 直链）。"""
    from ..utils import parse_video_ref

    parsed = parse_video_ref(ref)
    bvid = parsed.get("bvid")
    if not bvid:
        raise ValueError("取流需要 BV 号或视频链接")
    view = client.request_json(C.EP_VIEW, params={"bvid": bvid}, wbi=True)
    aid = view.get("aid")
    cid = view.get("cid")

    data = client.request_json(
        C.EP_PLAYURL,
        params={"avid": aid, "bvid": bvid, "cid": cid, "qn": qn, "fnver": 0,
                "fnval": fnval, "fourk": 1, "gaia_source": "",
                "from_client": "BROWSER", "is_main_page": "true",
                "need_fragment": "false", "isGaiaAvoided": "false"},
        wbi=True,
        headers={"Referer": f"{C.WWW}/video/{bvid}/"},
    )

    dash = (data or {}).get("dash") or {}
    videos = [
        {
            "id": v.get("id"),
            "quality": QUALITY_LABEL.get(v.get("id"), str(v.get("id"))),
            "codecs": v.get("codecs"),
            "width": v.get("width"),
            "height": v.get("height"),
            "frame_rate": v.get("frameRate"),
            "bandwidth": v.get("bandwidth"),
            "mime_type": v.get("mimeType"),
            "base_url": v.get("baseUrl") or v.get("base_url"),
            "backup_urls": (v.get("backupUrl") or [])[:3],
        }
        for v in dash.get("video") or []
    ]
    audios = [
        {
            "id": a.get("id"),
            "bandwidth": a.get("bandwidth"),
            "codecs": a.get("codecs"),
            "base_url": a.get("baseUrl") or a.get("base_url"),
        }
        for a in dash.get("audio") or []
    ]
    durl = data.get("durl") or []

    return {
        "bvid": bvid,
        "aid": aid,
        "cid": cid,
        "title": view.get("title"),
        "duration": data.get("timelength"),
        "quality_now": data.get("quality"),
        "quality_now_label": QUALITY_LABEL.get(data.get("quality"), str(data.get("quality"))),
        "accept_quality": [
            {"qn": q, "label": QUALITY_LABEL.get(q, str(q))}
            for q in (data.get("accept_quality") or [])
        ],
        "formats": data.get("accept_description") or [],
        "dash": {"video": videos, "audio": audios, "duration": dash.get("duration")},
        "durl": [{"order": d.get("order"), "size": d.get("size"),
                  "url": d.get("url")} for d in durl],
        "media_headers": {
            "Referer": f"{C.WWW}/video/{bvid}/",
            "User-Agent": "(curl_cffi impersonate 会话自带)",
        },
        "note": "直链带时效签名，取到后请尽快使用；下载时需保持 Referer 与 UA 一致。",
    }

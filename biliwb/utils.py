"""输入解析与通用工具：BV/AV 互转、链接解析、广告参数提取。"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from typing import Any

# ---------------------------------------------------------------- BV <-> AV

XOR_CODE = 23442827791579
MASK_CODE = 2251799813685247
MAX_AID = 1 << 51
BASE = 58
ALPHABET = "FcwAPNKTMug3GV5Lj7EJnHpWsx4tb8haYeviqBz6rkCy12mUSDQX9RdoZf"
BV_RE = re.compile(r"BV[0-9A-Za-z]{10}")
AV_RE = re.compile(r"av(\d+)", re.IGNORECASE)


def av2bv(aid: int) -> str:
    chars = list("BV1000000000")
    idx = len(chars) - 1
    rest = (MAX_AID | int(aid)) ^ XOR_CODE
    while rest:
        chars[idx] = ALPHABET[rest % BASE]
        rest //= BASE
        idx -= 1
    chars[3], chars[9] = chars[9], chars[3]
    chars[4], chars[7] = chars[7], chars[4]
    return "".join(chars)


def bv2av(bvid: str) -> int:
    chars = list(bvid[3:])
    if len(chars) != 9:
        raise ValueError(f"BV 号长度非法: {bvid}")
    chars[0], chars[6] = chars[6], chars[0]
    chars[1], chars[4] = chars[4], chars[1]
    rest = 0
    for ch in chars:
        rest = rest * BASE + ALPHABET.index(ch)
    return (rest & MASK_CODE) ^ XOR_CODE


# ---------------------------------------------------------------- 输入识别

# 广告位专属参数（来源：本工作区参考文档 bilibili-commercial-video-fields.md）
AD_URL_PARAMS = (
    "creative_id", "linked_creative_id", "caid", "resource_id",
    "from_spmid", "source_id", "request_id",
)
# 投放宏：正常点击时由广告服务器替换，字面量出现说明拿到的是广告模板原始链接
AD_MACROS = ("__CAID__", "__RESOURCEID__", "__FROMSPMID__")
# 普通推荐位埋点，不构成广告证据
PLAIN_URL_PARAMS = ("spm_id_from", "vd_source", "trackid", "track_id", "buvid", "share_source")


def extract_ad_params(url: str) -> dict[str, Any]:
    """从 URL query 提取投放相关参数（未做判定，只做证据收集）。"""
    if not url or "?" not in url:
        return {}
    query = urllib.parse.parse_qs(url.split("?", 1)[1], keep_blank_values=True)
    flat = {k: (v[0] if v else "") for k, v in query.items()}
    hits = {k: flat[k] for k in AD_URL_PARAMS if k in flat}
    macros = [m for m in AD_MACROS if m in (flat.get(m, "") or "") or m in url]
    plain = {k: flat[k] for k in PLAIN_URL_PARAMS if k in flat}
    return {"ad_params": hits, "macros": macros, "plain_params": plain, "raw_url": url}


def parse_video_ref(text: str) -> dict[str, Any]:
    """接受 BV 号 / av 号 / 视频链接（含短链），返回 {bvid, aid, ad}。"""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("空的视频输入")
    ad = extract_ad_params(raw)

    m = BV_RE.search(raw)
    if m:
        bvid = m.group(0)
        return {"bvid": bvid, "aid": bv2av(bvid), "ad": ad, "input": raw}

    m = AV_RE.search(raw)
    if m:
        aid = int(m.group(1))
        return {"bvid": av2bv(aid), "aid": aid, "ad": ad, "input": raw}

    if "b23.tv" in raw:
        return {"short_url": raw, "ad": ad, "input": raw}

    raise ValueError(f"无法从输入中识别视频: {raw}")


SPACE_MID_RE = re.compile(r"space\.bilibili\.com/(\d+)")
UID_PURE_RE = re.compile(r"^\d{1,12}$")
UID_JSON_RE = re.compile(r'"mid"\s*:\s*(\d+)')


def parse_space_ref(text: str) -> dict[str, Any]:
    """接受 uid / 空间链接，返回 {mid}；用户名留给搜索接口解析。"""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("空的用户输入")
    m = SPACE_MID_RE.search(raw)
    if m:
        return {"mid": int(m.group(1)), "input": raw, "resolved_by": "space_url"}
    if raw.isdigit() and len(raw) <= 12:
        return {"mid": int(raw), "input": raw, "resolved_by": "uid"}
    # 其余一律当作用户名，交由 search(user) 解析
    return {"username": raw, "input": raw, "resolved_by": "username"}


def parse_duration(text: str) -> int:
    """把 "MM:SS" / "HH:MM:SS" 转成秒。"""
    if not text:
        return 0
    parts = [int(p) for p in str(text).split(":") if p.isdigit()]
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def ts_to_str(ts: Any) -> str:
    """10 位时间戳 -> 本地可读时间（空值返回空串）。"""
    try:
        value = int(ts)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))


def ms_to_clock(ms: Any) -> str:
    """毫秒 -> mm:ss（弹幕在视频中的位置）。"""
    try:
        total = int(ms) // 1000
    except (TypeError, ValueError):
        return ""
    return f"{total // 60:02d}:{total % 60:02d}"


def strip_html(text: Any) -> str:
    """搜索结果的 title 带 <em> 高亮标签，去掉。"""
    if not isinstance(text, str):
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()


# ---------------------------------------------------------------- 评论链接

# 评论正文里的链接：支持 http(s)://、协议相对 //host，以及裸短链
URL_IN_TEXT = re.compile(
    r"(?:https?:)?//[^\s，,。；;）)】\]\"'<>]+"
    r"|(?:b23\.tv|t\.cn|m\.tb\.cn|u\.jd\.com|item\.(?:taobao|jd)\.com)/[^\s，,。；;）)】\]\"'<>]*"
)

# 带货/电商域名（命中即视为商品类链接）
GOODS_HINTS = (
    "mall.bilibili.com", "b23.tv/mall", "item.taobao.com", "item.jd.com",
    "m.tb.cn", "u.jd.com", "detail.tmall.com", "yangkeduo.com", "pinduoduo.com",
)


def normalize_mid(value: Any) -> int | None:
    """uid 归一化为 int。

    实测坑：`x/v2/reply/wbi/main` 里 `member.mid` 是**字符串**（'542316830'），
    而 `x/web-interface/wbi/view` 里 `owner.mid` 是**整数**（542316830）。
    直接比较会恒为 False，导致"置顶评论是否作者本人"永远判错。
    """
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _goods_ad_signals(cache: Any) -> dict[str, Any]:
    """商品卡片的 `goods_prefetched_cache` 里携带的投放属性。

    实测（rpid 315741109936）：该 JSON 字符串含 `"is_ad_loc":true` 与
    `creative_id` —— 即 B 站商城 CPS 商品卡片自身就是广告位。
    """
    if not cache:
        return {}
    try:
        data = json.loads(cache) if isinstance(cache, str) else cache
    except (ValueError, TypeError):
        # 只吞"内容不是合法 JSON"，不吞 NameError/ImportError 这类我方缺陷
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    for key in ("is_ad_loc", "resource_id", "source_id", "server_type"):
        if key in data:
            out[key] = data[key]
    ad_content = data.get("ad_content") or {}
    if isinstance(ad_content, dict):
        for key in ("creative_id", "creative_type"):
            if ad_content.get(key) is not None:
                out[key] = ad_content[key]
    return out


def extract_comment_links(content: Any) -> list[dict[str, Any]]:
    """从评论 content 提取全部链接。

    权威来源是 `content.jump_url`（链接 -> 元信息），它不依赖正文里是否出现 URL
    字面量 —— 商品/视频/专栏卡片在正文里可能只有文字。正文正则作为补充。
    """
    content = content if isinstance(content, dict) else {}
    links: list[dict[str, Any]] = []
    seen: set[str] = set()

    jump = content.get("jump_url") or {}
    if isinstance(jump, dict):
        for url, meta in jump.items():
            if not url:
                continue
            meta = meta if isinstance(meta, dict) else {}
            extra = meta.get("extra") or {}
            goods_id = extra.get("goods_item_id") if isinstance(extra, dict) else None
            signals = _goods_ad_signals(extra.get("goods_prefetched_cache")
                                        if isinstance(extra, dict) else None)
            is_goods = bool(goods_id) or any(h in str(url) for h in GOODS_HINTS)
            links.append({
                "url": str(url),
                "title": meta.get("title"),
                "source": "jump_url",
                "kind": "goods" if is_goods else "link",
                "goods_item_id": goods_id,
                "ad_signals": signals,
            })
            seen.add(str(url))

    message = content.get("message") or ""
    for match in URL_IN_TEXT.finditer(message):
        raw = match.group(0)
        if raw.startswith("//"):
            url = "https:" + raw
        elif not raw.startswith("http"):
            url = "https://" + raw
        else:
            url = raw
        if url in seen:
            continue
        seen.add(url)
        links.append({
            "url": url,
            "title": None,
            "source": "message",
            "kind": "goods" if any(h in url for h in GOODS_HINTS) else "link",
            "goods_item_id": None,
            "ad_signals": {},
        })
    return links


def find_first_url(text: Any) -> str | None:
    """从纯文本里提取第一个链接（保留给 message 兜底使用）。"""
    if not isinstance(text, str):
        return None
    match = URL_IN_TEXT.search(text)
    if not match:
        return None
    raw = match.group(0)
    if raw.startswith("//"):
        return "https:" + raw
    if raw.startswith("http"):
        return raw
    return "https://" + raw

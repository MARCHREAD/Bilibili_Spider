"""投流（ad）与接广（promo）判定。

判定口径（严格按需求方给的规则）
--------------------------------
* **投流 ad**：出现「ad 字段特征」即为投流，**与有没有置顶评论外挂链接无关**。
* **接广 promo**：**没有** ad 字段特征，但出现「作者本人置顶评论 + 外挂链接」。
* 两者互斥地落到 category：`ad` / `promo` / `organic`。

ad 字段特征的可信度分层（依据参考文档 bilibili-commercial-video-fields.md 的实测结论）
--------------------------------------------------------------------------------------
★★★★★ URL 命中 `creative_id` / `linked_creative_id` -> 该次访问来自广告位
★★★★☆ URL 命中 ≥2 个投放宏（`__CAID__` / `__RESOURCEID__` / `__FROMSPMID__`）
★☆☆☆☆ 页面级 `adData` / `is_ad_loc` / `cm_mark` -> **页面广告位，与视频无关，必须排除**
☆☆☆☆☆ `copyright` / `adInfo` / `argue_info` -> 与广告无关（易误判，已排除）

重要边界（会写进返回值，避免过度断言）
------------------------------------
公开 web 端**不存在**"是不是商单（花火任务）"的字段。"有投放痕迹"只能说明这条
视频被花钱推过，不等于商单：UP 主自费投放（起飞）会留下完全一样的痕迹。
"""

from __future__ import annotations

from typing import Any

from .utils import extract_comment_links, find_first_url, normalize_mid

# 参考文献里明确"不能用来判断"的字段，列在此处是为了显式排除而非使用
EXCLUDED_FIELDS = ("copyright", "adInfo", "ad_info", "argue_info", "is_story", "honor_reply")

CATEGORY_AD = "ad"
CATEGORY_PROMO = "promo"
CATEGORY_ORGANIC = "organic"

CATEGORY_LABEL = {
    CATEGORY_AD: "投流（广告位来源）",
    CATEGORY_PROMO: "接广（作者置顶评论外挂链接）",
    CATEGORY_ORGANIC: "普通内容",
}


def judge_traffic(url: str, page_ad_flags: dict | None = None) -> dict[str, Any]:
    """判定该次访问是否来自广告位（= ad 字段特征）。

    `page_ad_flags` 为页面级取证的原始字段（仅作展示，不参与判定）。
    """
    from .utils import extract_ad_params

    parsed = extract_ad_params(url or "")
    ad_params = parsed.get("ad_params", {})
    macros = set(parsed.get("macros", []))
    evidence: list[str] = []
    strength = 0

    if "creative_id" in ad_params:
        evidence.append(f"URL 含 creative_id={ad_params['creative_id']}")
        strength = max(strength, 5)
    if "linked_creative_id" in ad_params:
        evidence.append(f"URL 含 linked_creative_id={ad_params['linked_creative_id']}")
        strength = max(strength, 5)
    if len(macros) >= 2:
        evidence.append("URL 含 ≥2 个投放宏: " + ", ".join(sorted(macros)))
        strength = max(strength, 4)
    if ad_params.get("source_id"):
        evidence.append(f"URL 含 source_id={ad_params['source_id']}（广告位 ID）")

    is_ad = strength >= 4
    if not is_ad and parsed.get("plain_params"):
        evidence.append("仅有普通推荐位埋点: " + ", ".join(sorted(parsed["plain_params"])))

    return {
        "is_ad": is_ad,
        "evidence_strength": strength,
        "evidence": evidence,
        "ad_params": ad_params,
        "plain_params": parsed.get("plain_params", {}),
        "page_ad_flags": page_ad_flags or {},
        "note": "有投放痕迹只说明该视频被花钱推过，不等于商单；UP 主自费投放痕迹相同。",
        "excluded_fields": list(EXCLUDED_FIELDS),
    }


def judge_promo(top_comment: dict | None, up_mid: Any) -> dict[str, Any]:
    """判定「接广」：置顶评论由**作者本人**发出，且正文外挂链接。

    两个实测坑（都会导致漏判）：
      1. `member.mid` 是字符串、`owner.mid` 是整数 -> 必须归一化后比较；
      2. 带货链接的权威来源是 `content.jump_url`，商品卡片在正文里可能只有文字，
         光靠正文正则找不到 —— 所以要吃 `links`（由 extract_comment_links 产出）。
    """
    if not top_comment:
        return {"is_promo": False, "is_author": False, "link": None, "links": [],
                "has_link": False, "has_goods_link": False, "goods_links": [],
                "comment_mid": None, "evidence": ["没有置顶评论"]}

    raw_mid = top_comment.get("mid")
    if raw_mid in (None, ""):
        raw_mid = (top_comment.get("member") or {}).get("mid")
    comment_mid = normalize_mid(raw_mid)
    author_mid = normalize_mid(up_mid)

    links = top_comment.get("links")
    if links is None:
        links = extract_comment_links({"message": top_comment.get("message")})
    links = list(links or [])
    goods_links = [l for l in links if l.get("kind") == "goods"]
    link = links[0].get("url") if links else None

    is_author = bool(author_mid) and comment_mid == author_mid

    # 商品卡片自带的投放属性（B 站商城 CPS 卡片实测含 is_ad_loc / creative_id）
    commerce: dict[str, Any] = {}
    for item in goods_links:
        for key, value in (item.get("ad_signals") or {}).items():
            commerce.setdefault(key, value)

    evidence = [f"置顶评论作者 mid={comment_mid}（原始值 {raw_mid!r}）",
                f"视频作者 mid={author_mid}"]
    evidence.append("置顶评论由视频作者本人发出" if is_author
                    else "置顶评论不是视频作者本人发出（不构成接广）")
    if links:
        evidence.append(f"置顶评论外挂 {len(links)} 个链接: "
                        + ", ".join(f"{l.get('kind')}:{l.get('url')}" for l in links[:3]))
    else:
        evidence.append("置顶评论没有外链")
    if goods_links:
        evidence.append(f"其中 {len(goods_links)} 个是商品卡片"
                        + (f"（goods_item_id={goods_links[0].get('goods_item_id')}）"
                           if goods_links[0].get("goods_item_id") else ""))
    if commerce:
        evidence.append("商品卡片自带投放属性: "
                        + ", ".join(f"{k}={v}" for k, v in commerce.items()))

    return {
        "is_promo": bool(is_author and links),
        "is_author": is_author,
        "link": link,
        "links": links,
        "has_link": bool(links),
        "has_goods_link": bool(goods_links),
        "goods_links": goods_links,
        "commerce_signals": commerce,
        "comment_mid": comment_mid,
        "comment_message": (top_comment.get("message") or "")[:300],
        "rpid": top_comment.get("rpid"),
        "evidence": evidence,
        "note": ("商品卡片自带 is_ad_loc/creative_id 说明它是 B 站商城推广位，"
                 "但这是**评论商品卡片**的广告属性，不是视频自身的 ad 字段特征，"
                 "因此按规则仍计入「接广」而不是「投流」。"),
    }


def combine(traffic: dict, promo: dict) -> dict[str, Any]:
    """按需求规则合成最终分类（ad 优先，与置顶评论无关）。"""
    if traffic.get("is_ad"):
        category = CATEGORY_AD
        reason = "命中 ad 字段特征（URL 投放参数），按规则直接判定为投流，与置顶评论无关"
    elif promo.get("is_promo"):
        category = CATEGORY_PROMO
        extra = "，且置顶评论是商品卡片" if promo.get("has_goods_link") else ""
        reason = f"无 ad 字段特征，但作者本人置顶评论外挂链接{extra}，判定为接广"
    else:
        category = CATEGORY_ORGANIC
        reason = "既无 ad 字段特征，也无作者置顶外挂链接"
    return {
        "category": category,
        "category_label": CATEGORY_LABEL[category],
        "is_ad": bool(traffic.get("is_ad")),
        "is_promo": category == CATEGORY_PROMO,
        "has_link_in_pinned": bool(promo.get("has_link")),
        "pinned_is_author": bool(promo.get("is_author")),
        "pinned_links": promo.get("links", []),
        "commerce_signals": promo.get("commerce_signals", {}),
        "reason": reason,
        "traffic_evidence": traffic.get("evidence", []),
        "promo_evidence": promo.get("evidence", []),
        "boundary": "商单（花火任务）在公开 web 端无字段可查；ad 仅表示本次访问来自广告位。",
    }


# ---------------------------------------------------------------- 页面级取证

PAGE_AD_DISCLOSURE = ("广告", "商业推广", "含商业推广信息")


def scan_page_ad_state(initial_state: dict) -> dict[str, Any]:
    """从视频页 __INITIAL_STATE__ 提取页面广告位信息（**不用于 per-video 判定**）。

    实测：两个样本（广告投放样本 vs 普通样本）的 adData 字段值完全相同，
    因此这些字段不能区分视频，只作展示与"已排除"的证明。
    """
    ad_data = (initial_state or {}).get("adData") or {}
    flags = []
    for slot, items in ad_data.items():
        for item in (items or []):
            if not isinstance(item, dict):
                continue
            flags.append({
                "slot": slot,
                "name": item.get("name"),
                "res_id": item.get("res_id"),
                "is_ad_loc": item.get("is_ad_loc"),
                "cm_mark": item.get("cm_mark"),
                "adver_name": item.get("adver_name"),
            })
    return {
        "ad_data_slots": list(ad_data.keys()),
        "flags": flags,
        "usable_for_video_verdict": False,
        "why": "页面广告位与视频内容无关；实测两个对照样本该字段值相同。",
    }


def scan_html_disclosure(html: str) -> dict[str, Any]:
    """在视频页 HTML 里查找「广告 / 商业推广」披露标签文本。"""
    hits = [word for word in PAGE_AD_DISCLOSURE if word in (html or "")]
    return {
        "disclosure_words": hits,
        "has_disclosure": bool(hits),
        "note": "披露标签是页面文本，不是结构化字段；命中只作旁证。",
    }

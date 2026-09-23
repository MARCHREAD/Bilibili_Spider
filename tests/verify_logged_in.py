"""登录态专项验证：逐一确认"必须登录"的字段/能力是否已解锁，并保留负对照。

用法：python tests/verify_logged_in.py [--port 8765] [--uid <自己的uid>]
stdout = 机器可读 JSON 报告；stderr = 逐项人类可读结果。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

PRIVACY_HIDDEN_UID = 480959917   # 良田田田：space/setting 里 disable_following=1，作隐私负对照
AD_URL = ("https://www.bilibili.com/video/BV1X9eb6tEvy/?caid=__CAID__"
          "&resource_id=__RESOURCEID__&from_spmid=__FROMSPMID__&source_id=5637"
          "&creative_id=3557007068")
NORMAL_BV = "BV1BHez6cEEm"
PROMO_BV = "BV1Pg8Z62E3C"        # 作者本人置顶评论挂 b23.tv 商城商品卡片 -> 接广正样本


def call(base: str, path: str, payload: dict | None = None, method: str | None = None,
         timeout: int = 240):
    """method=None 时：带 body 用 POST，不带 body 用 GET。"""
    data = json.dumps(payload).encode() if payload is not None else None
    verb = method or ("POST" if data is not None else "GET")
    req = urllib.request.Request(
        base + path, data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=verb)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--uid", type=int, default=0)
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    st = call(base, "/api/status", method="GET")
    if not st.get("ok"):
        print(f"服务未就绪: {st}", file=sys.stderr)
        return 2
    accounts = st["data"].get("accounts") or []
    if not accounts:
        print("没有账号，请先在界面里添加并登录", file=sys.stderr)
        return 2
    acc = next((a for a in accounts if a.get("last_status") == "ok"), accounts[0])
    me = call(base, f"/api/accounts/{acc['id']}/verify", {}, method="POST")
    if not me.get("ok") or not me.get("data", {}).get("ok"):
        print(f"账号「{acc['alias']}」未登录，无法执行登录态验证: "
              f"{me.get('error') or (me.get('data') or {}).get('error')}", file=sys.stderr)
        return 2
    my_uid = args.uid or int(me["data"]["mid"])
    print(f"当前账号: {me['data']['uname']} (uid {my_uid})", file=sys.stderr)

    report: dict = {"uid": my_uid, "checks": {}}

    def record(name: str, ok: bool, detail: str):
        report["checks"][name] = {"ok": ok, "detail": detail}
        print(f"  [{'OK ' if ok else 'BAD'}] {name:<34} {detail}", file=sys.stderr)

    # --- 1. 字幕
    body = call(base, "/api/call", {"kind": "video", "target": NORMAL_BV,
                                    "options": {"with_subtitle": True,
                                                "with_subtitle_text": True,
                                                "with_tags": False,
                                                "with_pinned_comment": False}})
    if body.get("ok"):
        subs = (body["data"].get("subtitle") or {}).get("subtitles") or []
        body_lines = sum(len(s.get("body") or []) for s in subs)
        record("字幕列表", len(subs) > 0, f"{len(subs)} 条轨，正文 {body_lines} 行")
        for s in subs[:3]:
            record(f"  字幕轨 {s.get('lan')}", bool(s.get("lan_doc")),
                   f"{s.get('lan_doc')} ai={s.get('ai_status')}")
    else:
        record("字幕列表", False, body.get("error", ""))

    # --- 2. 播放数/获赞数
    body = call(base, "/api/call", {"kind": "user", "target": str(my_uid), "options": {}})
    if body.get("ok"):
        d = body["data"]
        record("获赞数 likes", d.get("likes") is not None, str(d.get("likes")))
        record("播放数 play", d.get("play") is not None, str(d.get("play")))
        record("动态数 dynamic_count", True, f"{d.get('dynamic_count')} (类型 {type(d.get('dynamic_count')).__name__})")
        record("充电人数 charging_count", d.get("charging_count") is not None,
               str(d.get("charging_count")))
    else:
        record("用户资料", False, body.get("error", ""))

    # --- 3. 关系链：自己（应可见） vs 隐私用户（应明确受限）
    body = call(base, "/api/call", {"kind": "user", "target": str(my_uid),
                                    "options": {"with_followings": True,
                                                "with_followers": True, "list_pages": 1}})
    if body.get("ok"):
        d = body["data"]
        fo = d.get("followings") or {}
        fr = d.get("followers") or {}
        record("自己的关注名单", bool(fo.get("items")),
               f"available={fo.get('available')} count={fo.get('count')} reason={fo.get('reason')}")
        record("自己的粉丝名单", bool(fr.get("items")),
               f"available={fr.get('available')} count={fr.get('count')} reason={fr.get('reason')}")
    else:
        record("关系链", False, body.get("error", ""))

    body = call(base, "/api/call", {"kind": "user", "target": str(PRIVACY_HIDDEN_UID),
                                    "options": {"with_followings": True, "with_followers": True}})
    if body.get("ok"):
        fo = body["data"].get("followings") or {}
        record("隐私负对照: 对方关注列表被隐藏", fo.get("available") is False,
               f"available={fo.get('available')} reason={fo.get('reason')}")
    else:
        record("隐私负对照", False, body.get("error", ""))

    # --- 4. 评论翻页
    pages = []
    for page in (1, 2, 3):
        body = call(base, "/api/call", {"kind": "comments", "target": NORMAL_BV,
                                        "options": {"page": page, "page_size": 20,
                                                    "with_sub": False}})
        if body.get("ok"):
            d = body["data"]
            first = (d.get("items") or [{}])[0]
            pages.append((page, d.get("count"), d.get("is_end"),
                          (first.get("member") or {}).get("uname")))
        else:
            pages.append((page, None, None, body.get("error")))
    record("评论翻页", any(p[1] for p in pages), str(pages))

    # --- 5. 动态 + 动态数量（feed/space 的 total 不可靠 -> 翻页累计）
    body = call(base, "/api/call", {"kind": "dynamics", "target": str(my_uid), "options": {}})
    if body.get("ok"):
        d = body["data"]
        record("动态列表", d.get("count", 0) > 0 or d.get("total") is not None,
               f"count={d.get('count')} total={d.get('total')} has_more={d.get('has_more')}")
    else:
        record("动态列表", False, body.get("error", ""))

    body = call(base, "/api/call", {"kind": "user", "target": str(PRIVACY_HIDDEN_UID),
                                    "options": {"with_dynamic_scan": True}})
    if body.get("ok"):
        d = body["data"]
        record("动态数(翻页累计)", d.get("dynamic_count_method") == "paged_scan",
               f"dynamic_count={d.get('dynamic_count')} method={d.get('dynamic_count_method')} "
               f"err={list((d.get('errors') or {}).keys())}")
    else:
        record("动态数(翻页累计)", False, body.get("error", ""))

    # --- 6. 广告判定在登录态下仍正确（回归）
    body = call(base, "/api/call", {"kind": "video", "target": AD_URL,
                                    "options": {"with_subtitle": False, "with_tags": False,
                                                "with_pinned_comment": True}})
    if body.get("ok"):
        v = body["data"].get("ad_verdict") or {}
        record("投流判定回归(带广告参数)", v.get("category") == "ad", str(v.get("category")))
    body = call(base, "/api/call", {"kind": "video", "target": NORMAL_BV,
                                    "options": {"with_subtitle": False, "with_tags": False,
                                                "with_pinned_comment": True}})
    if body.get("ok"):
        v = body["data"].get("ad_verdict") or {}
        record("投流判定回归(普通视频)", v.get("category") in ("organic", "promo"),
               str(v.get("category")))

    # 接广正样本：作者本人置顶评论挂 B 站商城商品卡片
    body = call(base, "/api/call", {"kind": "video", "target": PROMO_BV,
                                    "options": {"with_subtitle": False, "with_tags": False,
                                                "with_pinned_comment": True}})
    if body.get("ok"):
        v = body["data"].get("ad_verdict") or {}
        pc = body["data"].get("pinned_comment") or {}
        links = pc.get("links") or []
        record("接广正样本(BV1Pg8Z62E3C)",
               v.get("category") == "promo" and bool(links),
               f"category={v.get('category')} pinned_source={pc.get('pinned_source')} "
               f"links={len(links)} goods={v.get('commerce_signals')}")
        record("  置顶评论作者归属正确", v.get("pinned_is_author") is True,
               f"pinned_mid={pc.get('mid')}")
    else:
        record("接广正样本(BV1Pg8Z62E3C)", False, body.get("error", ""))

    ok_n = sum(1 for c in report["checks"].values() if c["ok"])
    report["ok_count"] = ok_n
    report["total"] = len(report["checks"])
    print(f"\n{ok_n}/{len(report['checks'])} 通过", file=sys.stderr)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

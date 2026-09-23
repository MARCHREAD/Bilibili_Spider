"""端到端 smoke：通过本地工作台 HTTP API 逐个调用 8 项能力。

用法：
    python main.py --no-browser          # 另开一个窗口先启动服务
    python tests/test_server.py [--port 8765]

输出：stdout 为机器可读 JSON 摘要；stderr 为逐项人类可读结果。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

AD_URL = ("https://www.bilibili.com/video/BV1X9eb6tEvy/?caid=__CAID__"
          "&resource_id=__RESOURCEID__&from_spmid=__FROMSPMID__&source_id=5637"
          "&creative_id=3557007068&linked_request_id=1&request_id=1790064519651q10a88a112a128q5343")
NORMAL = "BV1BHez6cEEm"
MID = 480959917


def call(base: str, path: str, payload: dict | None = None, method: str | None = None,
         timeout: int = 180):
    """method=None 时：带 body 用 POST，不带 body 用 GET。"""
    data = json.dumps(payload).encode() if payload is not None else None
    verb = method or ("POST" if data is not None else "GET")
    req = urllib.request.Request(
        base + path, data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=verb,
    )
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


def summarize(kind: str, data) -> str:
    if not isinstance(data, dict):
        return f"{type(data).__name__}"
    if kind == "search":
        return f"total={data.get('total')} count={data.get('count')} first={(data.get('items') or [{}])[0].get('bvid')}"
    if kind == "video":
        v = data.get("ad_verdict") or {}
        st = data.get("stat") or {}
        return (f"{data.get('bvid')} view={st.get('view')} like={st.get('like')} "
                f"coin={st.get('coin')} fav={st.get('favorite')} share={st.get('share')} "
                f"tags={len(data.get('tags') or [])} 字幕={len((data.get('subtitle') or {}).get('subtitles') or [])} "
                f"判定={v.get('category')}")
    if kind == "comments":
        items = data.get("items") or []
        first = items[0] if items else {}
        return (f"all_count={data.get('all_count')} count={len(items)} "
                f"first=({(first.get('member') or {}).get('uname')},"
                f"lv{(first.get('member') or {}).get('level')}) "
                f"二级={len(first.get('sub_comments') or [])}")
    if kind == "danmaku":
        return (f"count={data.get('count')} 段数={data.get('segment_total')} "
                f"segments={data.get('segments_fetched')}")
    if kind == "user":
        return (f"{data.get('name')} uid={data.get('uid')} 粉丝={data.get('follower')} "
                f"关注={data.get('following')} 视频={data.get('video_count')} "
                f"动态={data.get('dynamic_count')} 获赞={data.get('likes')} 播放={data.get('play')} "
                f"充电={data.get('charging_count')} "
                f"关注隐私={((data.get('privacy') or {}).get('following_hidden'))}")
    if kind == "user_videos":
        return f"total={data.get('total')} count={data.get('count')} hint={data.get('hint')}"
    if kind == "stream":
        dash = data.get("dash") or {}
        return (f"quality={data.get('quality_now_label')} "
                f"视频轨={len(dash.get('video') or [])} 音频轨={len(dash.get('audio') or [])}")
    if kind == "dynamics":
        return f"total={data.get('total')} count={data.get('count')} has_more={data.get('has_more')}"
    return str(list(data)[:6])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    status = call(base, "/api/status")
    if not status.get("ok"):
        print(f"服务未就绪: {status}", file=sys.stderr)
        return 2
    data = status["data"]
    accounts = data.get("accounts") or []
    print(f"服务在线 v{data['version']} 账号={data['account_count']} "
          f"健康={data['healthy_count']} workers={data['workers']['workers']}", file=sys.stderr)
    if not accounts:
        print("没有账号，请先在界面里添加并登录", file=sys.stderr)
        return 2

    warm = call(base, f"/api/accounts/{accounts[0]['id']}/verify", {}, method="POST")
    print(f"主账号校验: {'OK' if warm.get('ok') and warm['data'].get('ok') else warm.get('error')}",
          file=sys.stderr)

    plan = [
        ("search", "原神", {"order": "click", "page": 1, "page_size": 30, "duration": 0}),
        ("video", AD_URL, {"with_subtitle": True, "with_tags": True, "with_pinned_comment": True}),
        ("video", NORMAL, {"with_subtitle": True, "with_tags": True, "with_pinned_comment": True}),
        ("comments", NORMAL, {"page": 1, "page_size": 20, "with_sub": True, "sub_pages": 1}),
        ("danmaku", NORMAL, {"all_segments": True}),
        ("user", str(MID), {}),
        ("user_videos", str(MID), {"page": 1, "page_size": 10, "order": "pubdate"}),
        ("stream", NORMAL, {"qn": 80}),
        ("dynamics", str(MID), {"page": 1}),
    ]

    report = {"port": args.port, "results": {}}
    ok_count = 0
    for kind, target, options in plan:
        body = call(base, "/api/call", {"kind": kind, "target": target, "options": options})
        key = f"{kind}:{target[:28]}"
        if body.get("ok"):
            ok_count += 1
            line = summarize(kind, body["data"])
            print(f"[OK]   {key:<46} {line}", file=sys.stderr)
            report["results"][key] = {"ok": True, "summary": line}
        else:
            print(f"[FAIL] {key:<46} {body.get('error')}", file=sys.stderr)
            report["results"][key] = {"ok": False, "error": body.get("error"),
                                      "code": body.get("code")}

    report["ok_count"] = ok_count
    report["total"] = len(plan)
    report["logged_in"] = bool(warm.get("ok") and warm.get("data", {}).get("ok"))
    print(f"\n{ok_count}/{len(plan)} 通过（账号 {accounts[0]['alias']} "
          f"登录态={report['logged_in']}）", file=sys.stderr)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

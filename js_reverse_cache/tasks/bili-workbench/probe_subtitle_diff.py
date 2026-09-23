"""对比 with_subtitle / with_subtitle_text 的实际差异（live，走工作台 API）。"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8765/api/call"
BV = "BV1BHez6cEEm"
COMMON = {"with_tags": False, "with_pinned_comment": False}


def call(options: dict) -> dict:
    body = json.dumps({"kind": "video", "target": BV, "options": options}).encode()
    req = urllib.request.Request(BASE, data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=300) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    if not out.get("ok"):
        raise SystemExit(f"调用失败: {out.get('error')}")
    return out["data"]


def describe(label: str, data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    sub = data.get("subtitle") or {}
    subs = sub.get("subtitles") or []
    lines = sum(len(s.get("body") or []) for s in subs)
    print(f"\n=== {label} ===", file=sys.stderr)
    print(f"  整个 video 响应大小: {len(payload):,} 字符", file=sys.stderr)
    print(f"  subtitle.source     : {sub.get('source')}", file=sys.stderr)
    print(f"  字幕轨数             : {len(subs)}", file=sys.stderr)
    print(f"  带 body 的轨数       : {sum(1 for s in subs if s.get('body'))}", file=sys.stderr)
    print(f"  正文总行数           : {lines}", file=sys.stderr)
    if subs:
        print(f"  第一轨字段           : {list(subs[0].keys())}", file=sys.stderr)
        print(f"  第一轨元信息         : lan={subs[0].get('lan')} "
              f"lan_doc={subs[0].get('lan_doc')} ai_status={subs[0].get('ai_status')} "
              f"url={str(subs[0].get('subtitle_url'))[:70]}…", file=sys.stderr)
        if subs[0].get("body"):
            print(f"  正文前 2 行          : "
                  f"{json.dumps(subs[0]['body'][:2], ensure_ascii=False)}", file=sys.stderr)


def main() -> int:
    off = call({**COMMON, "with_subtitle": False})
    meta = call({**COMMON, "with_subtitle": True, "with_subtitle_text": False})
    full = call({**COMMON, "with_subtitle": True, "with_subtitle_text": True})

    describe("A. with_subtitle=False（不取字幕）", off)
    describe("B. with_subtitle=True, with_subtitle_text=False（只取元信息）", meta)
    describe("C. with_subtitle=True, with_subtitle_text=True（含正文）", full)

    print("\n=== 结论 ===", file=sys.stderr)
    print(f"  B 比 A 多: 字幕轨元信息（{len((meta.get('subtitle') or {}).get('subtitles') or [])} 条轨，"
          f"每条含 lan/lan_doc/ai_status/subtitle_url）", file=sys.stderr)
    print(f"  C 比 B 多: 每条轨的 body 正文数组，共 "
          f"{sum(len(s.get('body') or []) for s in ((full.get('subtitle') or {}).get('subtitles') or []))} 行；"
          f"响应体积 {len(json.dumps(meta, ensure_ascii=False)):,} -> "
          f"{len(json.dumps(full, ensure_ascii=False)):,} 字符", file=sys.stderr)
    print(f"  请求成本: B 额外 1~2 次请求；C 再额外 N 次（每条字幕轨 1 次，N={len((full.get('subtitle') or {}).get('subtitles') or [])}）",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

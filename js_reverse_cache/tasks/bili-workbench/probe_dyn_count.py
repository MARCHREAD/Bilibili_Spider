"""诊断"动态数量"的可靠来源：feed/space 的 total/update_num 语义 + 空间页 HTML。"""

from __future__ import annotations

import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from biliwb import constants as C  # noqa: E402
from biliwb.client import BiliClient  # noqa: E402

MIDS = [494757969, 480959917]     # 自己 + 良田田田


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    cli = BiliClient(cookie_file=str(here / "session.txt"), min_delay=1.2, retries=2)
    cli.bootstrap()
    cli.warmup()
    cli.gen_ticket()
    cli.wbi_keys(refresh=True)

    for mid in MIDS:
        print(f"\n=== mid={mid} ===", file=sys.stderr)
        try:
            d = cli.request_json(C.EP_DYN_SPACE, params={
                "host_mid": mid, "web_location": 333.1387, "timezone_offset": -480})
            meta = {k: v for k, v in d.items() if k != "items"}
            print(f"  feed/space 元信息: {json.dumps(meta, ensure_ascii=False)[:300]}", file=sys.stderr)
            print(f"  本批 items={len(d.get('items') or [])}", file=sys.stderr)
        except Exception as exc:
            print(f"  feed/space 失败: {exc}", file=sys.stderr)

        # 翻页累计（最多 5 批）确认能否得到真实总数
        total_seen, offset, batches = 0, "", 0
        while batches < 5:
            params = {"host_mid": mid, "web_location": 333.1387, "timezone_offset": -480}
            if offset:
                params["offset"] = offset
            try:
                d = cli.request_json(C.EP_DYN_SPACE, params=params)
            except Exception as exc:
                print(f"  翻页 {batches+1} 失败: {exc}", file=sys.stderr)
                break
            n = len(d.get("items") or [])
            total_seen += n
            batches += 1
            offset = d.get("offset") or ""
            if not d.get("has_more") or not offset:
                break
        print(f"  翻页累计: {batches} 批 -> {total_seen} 条 (has_more 结束)", file=sys.stderr)

        # 空间页 HTML 里是否有动态数
        try:
            html = cli.get_text(f"https://space.bilibili.com/{mid}/dynamic",
                                headers={"Referer": "https://space.bilibili.com/"})
            hits = re.findall(r'"(?:dynamic_count|dyn_count|total)"\s*:\s*"?(\d+)"?', html)
            print(f"  空间页 HTML {len(html)}B, 候选计数命中: {hits[:8]}", file=sys.stderr)
        except Exception as exc:
            print(f"  空间页失败: {exc}", file=sys.stderr)

    print(f"\nhttp_calls={cli.http_calls}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

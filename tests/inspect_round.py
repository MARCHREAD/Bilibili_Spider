"""Inspect the last round's protocol.json: do all geetest calls use the SAME challenge?"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.parse

TASK = pathlib.Path(r"A:\agent\work\bilibili\js_reverse_cache\tasks\bili-gt3-solver")
CACHE = TASK / "cache"

dirs = sorted([d for d in CACHE.glob("proto_*") if d.is_dir()],
              key=lambda d: d.stat().st_mtime)
d = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else dirs[-1]
print("round dir:", d)
proto = json.loads((d / "protocol.json").read_text(encoding="utf-8"))
base = proto.get("base_challenge")
print("bili-issued challenge:", base)
print("bili-issued token    :", proto.get("token"))
print("gt                   :", proto.get("gt"))
print("validate             :", proto.get("validate"), "score:", proto.get("score"))
print()
for r in proto.get("requests", []):
    print(f"  id={r['id']:<3} {r['kind']:<7} {r['path']}")
print()
# full URLs live in w_values only; re-derive from transcripts for others
for t in proto.get("transcripts", []):
    print("TRANSCRIPT", t.get("id"), t.get("url", "")[:160])
print()
wv = json.loads((d / "w_values.json").read_text(encoding="utf-8"))
for w in wv:
    q = urllib.parse.parse_qs(urllib.parse.urlparse(w["url"]).query, keep_blank_values=True)
    ch = (q.get("challenge") or [""])[0]
    print(f"  id={w['id']:<3} {w['path']:<45} challenge={ch} same_as_base={ch == base} w_len={len(w['value'])}")

"""Summarize the newest proto_* round: captured w values and server verdicts."""
from __future__ import annotations

import json
import pathlib
import sys

CACHE = pathlib.Path(__file__).resolve().parent / "cache"


def main() -> int:
    rounds = sorted([d for d in CACHE.glob("proto_*") if d.is_dir()], key=lambda d: d.name)
    if not rounds:
        print("no rounds")
        return 1
    d = rounds[-1]
    p = json.loads((d / "protocol.json").read_text(encoding="utf-8"))
    print(f"round: {d.name}  http_used={p.get('http_used')}")

    print("\n=== captured w values ===")
    for w in p.get("w_values") or []:
        print(f"  id={w['id']:>2} {w['path'].rsplit('/', 1)[-1]:<12} len={len(w['value']):>5} head={w['value'][:30]}")

    print("\n=== requests ===")
    for r in p.get("requests") or []:
        print(f"  id={r['id']:>2} {r['path'].rsplit('/', 1)[-1]:<12} params={sorted(r['params'])}")

    print("\n=== server verdicts ===")
    for t in p.get("transcripts") or []:
        name = t["url"].split("?")[0].rsplit("/", 1)[-1]
        body = " ".join(t["body"][:200].split())
        print(f"  {name:<12} {body}")

    print("\n=== round payload shape ===")
    import re as _re
    for t in p.get("transcripts") or []:
        name = t["url"].split("?")[0].rsplit("/", 1)[-1]
        m = _re.search(r"\(\s*(\{.*\})\s*\)\s*$", t["body"].strip(), _re.S)
        if not m:
            continue
        try:
            payload = json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            continue
        data = payload.get("data")
        if isinstance(data, dict):
            interesting = {k: data[k] for k in ("type", "result", "pic_type", "num", "spec", "sign", "gct_path", "challenge", "ypos", "theme") if k in data}
            print(f"  {name:<12} status={payload.get('status')} data_keys={sorted(data.keys())[:14]}")
            if interesting:
                print(f"               {json.dumps(interesting, ensure_ascii=True)[:300]}")

    done = p.get("helper_done") or {}
    print("\n=== helper ===")
    print("  log:", (done.get("log") or [])[:6])
    print("  errors:", (done.get("errors") or [])[:4])
    print("  diag:", (done.get("diag") or [])[:4])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Show every ajax.php verdict of the newest round, in order, with w shapes."""
from __future__ import annotations

import json
import pathlib

CACHE = pathlib.Path(__file__).resolve().parent / "cache"


def main() -> int:
    rounds = sorted([d for d in CACHE.glob("proto_*") if d.is_dir()], key=lambda d: d.name)
    p = json.loads((rounds[-1] / "protocol.json").read_text(encoding="utf-8"))
    n = 0
    for t in p.get("transcripts") or []:
        if "ajax.php" in t["url"]:
            n += 1
            print(f"  ajax#{n}: {' '.join(t['body'][:200].split())}")
    print("\nw shapes (submissions carry a dot + 256 hex tail):")
    for w in p.get("w_values") or []:
        v = w["value"]
        dot = v.rfind(".")
        tail = v[dot + 1:] if dot > 0 else ""
        hexok = bool(tail) and all(c in "0123456789abcdef" for c in tail)
        print(f"   id={w['id']:>2} path={w['path'].rsplit('/', 1)[-1]:<10} len={len(v):>5} dotAt={dot:>5} tailHex={hexok}")
    print("\ncall-widget formats:")
    for m in p.get("helper_other") or []:
        if m.get("type") == "call-widget":
            print(f"   {m.get('format')}: {str(m.get('result'))[:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

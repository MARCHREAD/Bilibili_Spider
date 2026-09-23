"""Print the pre-encryption payloads captured by the JSON.stringify hook."""
from __future__ import annotations

import json
import pathlib

CACHE = pathlib.Path(__file__).resolve().parent / "cache"


def main() -> int:
    rounds = sorted([d for d in CACHE.glob("proto_*") if d.is_dir()], key=lambda d: d.name)
    d = rounds[-1]
    p = json.loads((d / "protocol.json").read_text(encoding="utf-8"))
    done = p.get("helper_done") or {}
    pl = done.get("payloads") or []
    out = [f"round {d.name}: captured payloads = {len(pl)}"]
    for i, x in enumerate(pl):
        out.append(f"--- payload {i} keys={x['keys']} jsonlen={x['len']}")
        out.append("    " + x["sample"][:900])
    out.append("")
    out.append("w lengths: " + json.dumps([{"id": w["id"], "len": len(w["value"])} for w in (p.get("w_values") or [])]))
    (pathlib.Path(__file__).resolve().parent / "payloads.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out[:200]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

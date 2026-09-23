"""Summarize the newest proto round with w-shape analysis (final submissions carry a dot + RSA hex tail)."""
from __future__ import annotations

import json
import pathlib
import sys

CACHE = pathlib.Path(__file__).resolve().parent / "cache"


def main() -> int:
    rounds = sorted([d for d in CACHE.glob("proto_*") if d.is_dir()], key=lambda d: d.name)
    d = rounds[-1]
    p = json.loads((d / "protocol.json").read_text(encoding="utf-8"))
    lines = [f"round {d.name} http_used={p.get('http_used')}", "", "=== requests ==="]
    for r in p.get("requests") or []:
        lines.append(f"  id={r['id']:>2} {r['kind']:<7} {r['path'].rsplit('/', 1)[-1][:44]:<44} {sorted(r['params'])[:6]}")

    lines += ["", "=== w shapes ==="]
    for w in p.get("w_values") or []:
        v = w["value"]
        dot = v.rfind(".")
        tail = v[dot + 1:] if dot > 0 else ""
        hexok = bool(tail) and all(c in "0123456789abcdef" for c in tail)
        lines.append(f"  id={w['id']:>2} {w['path'].rsplit('/', 1)[-1]:<11} len={len(v):>5} dotAt={dot:>5} tailLen={len(tail):>4} tailHex={hexok}")

    lines += ["", "=== verdicts ==="]
    for t in p.get("transcripts") or []:
        lines.append(f"  {t['url'].split('?')[0].rsplit('/', 1)[-1]:<12} {' '.join(t['body'][:150].split())}")

    done = p.get("helper_done") or {}
    lines += ["", "=== helper ===",
              f"  pendingTimers: {done.get('pendingTimers')}",
              f"  errors: {json.dumps(done.get('errors'), ensure_ascii=True)[:300]}"]
    probes = [m for m in (p.get("helper_other") or []) if m.get("type") == "probe"]
    if probes:
        lines.append(f"  probe calls: {len(probes)}; trigger: {json.dumps([m for m in (p.get('helper_other') or []) if m.get('type')=='probe-trigger'], ensure_ascii=True)[:200]}")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

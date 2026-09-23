"""Extract, per benchmark round, the round image behind each submit attempt.

Each retry downloads a NEW challenge image (pic_7.jpg, pic_12.jpg, ...), so a log's
download order maps one-to-one onto the solve order.

KNOWN LIMITATION -- do not turn this into an evidence archive
------------------------------------------------------------
Only the FILE NAME is recoverable here; the containing cache/proto_<stamp>/ directory is
not in the trace.  Every round downloads its first image as `pic_7.jpg`, so names collide
across rounds and across runs, and picking "the next proto_* dir" picks the wrong one.
An earlier attempt to archive images this way reproduced only 1/18 re-solved attempts and
was deleted.  To archive for real, log the absolute image path (gt3_protocol.py now emits
`pic_path` in its [solve] payload) instead of re-deriving it from the name.

usage: python map_attempt_images.py bench_logs_serial10
"""
from __future__ import annotations

import glob
import json
import pathlib
import re
import sys

TASK = pathlib.Path(__file__).resolve().parent
TIME = re.compile(r"\[t\+\s*([0-9.]+)s\]\s?")
OUTDIR = re.compile(r"\[http \d+\] \d+\s+\d+B\s+IMAGE pic -> (\S+)")


def main() -> int:
    dirs = sys.argv[1:] or ["bench_logs_serial10"]
    files = []
    for d in dirs:
        files += sorted(glob.glob(str(TASK / d / "round_*.log")))

    out = {}
    for f in files:
        p = pathlib.Path(f)
        text = p.read_text(encoding="utf-8", errors="replace")
        # every solve() writes a fresh proto_<stamp>/ dir; recover it from the trace order
        rounds = []
        cur = None
        for ln in text.splitlines():
            b = TIME.sub("", ln).strip()
            m = OUTDIR.search(b)
            if m:
                cur = {"pic": m.group(1)}
            sm = re.search(r"\[solve\] (\{.*\})", b)
            if sm:
                s = json.loads(sm.group(1))
                if cur is not None:
                    cur.update({"prompt": s.get("prompt"), "n": s.get("n"),
                                "ms": s.get("solve_ms"),
                                "fallback": sum(1 for x in (s.get("matches") or []) if x.get("fallback")),
                                "min_score": min([x.get("score") or 0 for x in (s.get("matches") or [])], default=None),
                                "points": s.get("points")})
                rounds.append(cur)
                cur = None
            if b.startswith("[verdict]") and "ajax.php" in b and rounds and "verdict" not in rounds[-1]:
                payload = b.split("-> ", 1)[-1]
                try:
                    rounds[-1]["verdict"] = (json.loads(payload).get("data") or {}).get("result")
                except Exception:  # noqa: BLE001
                    pass
        out[p.stem + "@" + p.parent.name] = rounds

    for key, rounds in out.items():
        print(f"{key}:")
        for r in rounds:
            v = r.get("verdict", "?")
            mark = "*" if v == "success" else " " if v == "fail" else "?"
            print(f"  {mark} {r.get('pic'):<12} verdict={v:<8} n={r.get('n')} fb={r.get('fallback')} "
                  f"min={r.get('min_score')} prompt={''.join(r.get('prompt') or [])} "
                  f"points={r.get('points')}")
    (TASK / "attempt_images.json").write_text(json.dumps(out, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"\nwritten attempt_images.json  ({sum(len(v) for v in out.values())} attempts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

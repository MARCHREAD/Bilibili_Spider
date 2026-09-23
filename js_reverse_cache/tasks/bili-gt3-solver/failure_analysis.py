"""Failure-mode attribution for GT3 benchmark logs.

The headline "N/N passed" hides the SDK's auto-refresh: a round can submit a wrong
answer, get {"result":"fail"}, receive a fresh challenge, and still finish green.
This script separates the two and correlates each solve with its own verdict.

usage: python failure_analysis.py bench_logs_serial10 bench_logs/bench_par2_10
"""
from __future__ import annotations

import glob
import json
import pathlib
import re
import statistics
import sys

TASK = pathlib.Path(__file__).resolve().parent
TIME = re.compile(r"\[t\+\s*([0-9.]+)s\]\s?")


def parse(path: pathlib.Path) -> dict:
    """Interleave solves and verdicts in time order so each solve maps to its verdict."""
    events = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = TIME.match(ln)
        t = float(m.group(1)) if m else None
        b = TIME.sub("", ln).strip()
        if b.startswith("[solve]"):
            s = json.loads(b[7:])
            matches = s.get("matches") or []
            events.append((t, "solve", {
                "pic": s.get("pic"), "ms": s.get("solve_ms"), "n": s.get("n"),
                "prompt": s.get("prompt"),
                "n_boxes": len(s.get("field_boxes") or []),
                "fallback": sum(1 for x in matches if x.get("fallback")),
                "scores": [x.get("score") for x in matches],
                "min_score": min([x.get("score") or 0 for x in matches], default=None),
                "mean_score": (sum(x.get("score") or 0 for x in matches) / len(matches))
                              if matches else None,
                "points": s.get("points"),
            }))
        elif b.startswith("[verdict]") and "ajax.php" in b:
            payload = b.split("-> ", 1)[-1]
            try:
                data = (json.loads(payload).get("data") or {})
                result = data.get("result")
            except Exception:  # noqa: BLE001
                result = "unparsed"
            events.append((t, "verdict", {"result": result,
                                          "validate": data.get("validate") if isinstance(data, dict) else None}))
        elif b.startswith("[round] gt=") or b.startswith("=== SUCCESS"):
            pass
    events.sort(key=lambda e: (e[0] if e[0] is not None else 0))
    return {"file": path.name, "events": events}


def pair(ev: dict) -> dict:
    """Attach the next answer verdict to each solve (the submit that used it)."""
    pairs, pending = [], None
    for _t, kind, payload in ev["events"]:
        if kind == "solve":
            pending = payload
        elif kind == "verdict" and payload["result"] in ("success", "fail") and pending:
            p = dict(pending)
            p["verdict"] = payload["result"]
            pairs.append(p)
            pending = None
        elif kind == "verdict" and payload["result"] == "click":
            continue
    return {"file": ev["file"], "attempts": pairs,
            "final_ok": any(p["verdict"] == "success" for p in pairs)}


def main() -> int:
    dirs = sys.argv[1:] or ["bench_logs_serial10"]
    files = []
    for d in dirs:
        files += sorted(glob.glob(str(TASK / d / "round_*.log")))
    rounds = [pair(parse(pathlib.Path(f))) for f in files]
    if not rounds:
        print("no logs found")
        return 1

    all_attempts = [a for r in rounds for a in r["attempts"]]
    first = [r["attempts"][0] for r in rounds if r["attempts"]]
    solved = [r for r in rounds if r["final_ok"]]

    print(f"log dirs            : {', '.join(dirs)}")
    print(f"rounds              : {len(rounds)}")
    print(f"final success       : {len(solved)}/{len(rounds)} = {len(solved)/len(rounds)*100:.1f}%")
    ok_first = sum(1 for a in first if a["verdict"] == "success")
    print(f"FIRST-ATTEMPT hit   : {ok_first}/{len(first)} = {ok_first/len(first)*100:.1f}%   <-- true per-submit accuracy")
    print(f"answer attempts     : {len(all_attempts)} over {len(rounds)} rounds "
          f"(mean {len(all_attempts)/len(rounds):.2f}/round)")
    ok_all = sum(1 for a in all_attempts if a["verdict"] == "success")
    print(f"per-submit accuracy : {ok_all}/{len(all_attempts)} = {ok_all/len(all_attempts)*100:.1f}%")
    dist: dict[int, int] = {}
    for r in rounds:
        dist[len(r["attempts"])] = dist.get(len(r["attempts"]), 0) + 1
    print(f"attempts/round dist : " + ", ".join(f"{k}x{v}" for k, v in sorted(dist.items())))

    def agg(key: str, pct: bool = False):
        out = {}
        for name, group in (("ok", [a for a in all_attempts if a["verdict"] == "success"]),
                            ("fail", [a for a in all_attempts if a["verdict"] == "fail"])):
            vals = [a[key] for a in group if a.get(key) is not None]
            if vals:
                out[name] = (round(statistics.median(vals), 2), round(sum(vals) / len(vals), 2), len(vals))
        return out

    print("\ncorrelates of an accepted submit (median / mean / n):")
    for key in ("n", "n_boxes", "fallback", "min_score", "mean_score", "ms"):
        print(f"  {key:<11} {agg(key)}")

    print("\nper-round attempt detail (* = accepted):")
    for r in rounds:
        bits = []
        for a in r["attempts"]:
            mark = "*" if a["verdict"] == "success" else " "
            bits.append(f"{mark}n={a['n']} fb={a['fallback']} min={a['min_score']} "
                        f"prompt={''.join(a['prompt'] or [])}")
        print(f"  {r['file']:<16} {' | '.join(bits)}")

    bad = [a for a in all_attempts if a["verdict"] == "fail"]
    print(f"\nfailed submits      : {len(bad)}")
    if bad:
        fb = [a["fallback"] for a in bad]
        okfb = [a["fallback"] for a in all_attempts if a["verdict"] == "success"]
        print(f"  fallback per failed submit: mean={sum(fb)/len(fb):.2f} "
              f"(accepted submits: mean={sum(okfb)/len(okfb):.2f})")
        zero = sum(1 for x in fb if x == 0)
        print(f"  failed submits with ZERO fallback (so pure misclick/misread): {zero}/{len(bad)}")
    (TASK / "failure_analysis.json").write_text(json.dumps(rounds, ensure_ascii=True, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

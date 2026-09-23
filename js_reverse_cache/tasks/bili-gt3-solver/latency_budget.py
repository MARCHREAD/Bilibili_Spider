"""Latency budget: split a round's wall time into network/SDK, solver and submit.

The driver sleeps 0.5 s before every SDK request, so request count largely explains
the non-solver part of a round.  This quantifies that instead of guessing.

usage: python latency_budget.py bench_logs_serial10
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
HTTP = re.compile(r"\[http (\d+)\]")


def parse(path: pathlib.Path) -> dict:
    marks = []
    http_times = []
    solve_ms = None
    t_verdict = t_solved = None
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = TIME.match(ln)
        t = float(m.group(1)) if m else None
        b = TIME.sub("", ln).strip()
        if m and HTTP.search(b):
            http_times.append(t)
        if b.startswith("[round] gt="):
            marks.append(("challenge", t))
        elif b.startswith("[solver]"):
            t_solved = t
        elif b.startswith("[verdict]") and "ajax.php" in b and '"success"' in b:
            t_verdict = t
        sm = re.search(r"\[solve\] (\{.*\})", b)
        if sm:
            s = json.loads(sm.group(1))
            if s.get("solve_ms"):
                solve_ms = max(solve_ms or 0, s["solve_ms"])
    return {"file": path.name, "http_count": len(http_times),
            "solve_ms": solve_ms,
            "last_http_t": http_times[-1] if http_times else None,
            "t_solved": t_solved, "t_verdict": t_verdict}


def main() -> int:
    dirs = sys.argv[1:] or ["bench_logs_serial10"]
    files = []
    for d in dirs:
        files += sorted(glob.glob(str(TASK / d / "round_*.log")))
    rows = [parse(pathlib.Path(f)) for f in files]

    http_counts = [r["http_count"] for r in rows]
    sleeps = [0.5 * c for c in http_counts]
    solves = [r["solve_ms"] for r in rows if r["solve_ms"]]

    print(f"rounds            : {len(rows)}")
    print(f"http requests/round: min={min(http_counts)} median={int(statistics.median(http_counts))} "
          f"max={max(http_counts)} (mean {statistics.mean(http_counts):.1f})")
    print(f"driver 0.5s sleeps : median {statistics.median(sleeps):.1f}s of each round "
          f"(mean {statistics.mean(sleeps):.1f}s)")
    if solves:
        print(f"total solver time  : median {statistics.median(solves)/1000:.2f}s "
              f"max {max(solves)/1000:.2f}s per round")

    # ratio of solver time to round time, using the serial benchmark report
    report = TASK / "bench_serial10.json"
    if report.exists():
        d = json.loads(report.read_text(encoding="utf-8"))
        prs = d["per_round_seconds"]
        print(f"\nper-round wall     : median {prs['median']}s mean {prs['mean']}s "
              f"min {prs['min']}s max {prs['max']}s")
        sm = d["solver_ms"]
        print(f"solver share       : median {sm['median']/1000:.2f}s of {prs['median']}s "
              f"= {sm['median']/1000/prs['median']*100:.0f}%")
        print(f"submit/ajax share  : median {d['submit_s']['median']}s")
        print(f"remainder (SDK/net): ~{prs['median'] - sm['median']/1000 - d['submit_s']['median']:.1f}s")
    (TASK / "latency_budget.json").write_text(json.dumps(rows, ensure_ascii=True, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

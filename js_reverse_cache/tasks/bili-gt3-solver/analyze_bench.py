"""Deep analysis of benchmark logs: attempts per round, retry reasons, phase budget.

Distinguishes "passes because it was right first time" from "passes after the SDK
auto-refreshed the challenge", which a plain success count hides.

usage: python analyze_bench.py bench_logs [more_dirs...]
"""
from __future__ import annotations

import glob
import json
import pathlib
import re
import statistics
import sys

TASK = pathlib.Path(__file__).resolve().parent
TIME_RE = re.compile(r"\[t\+\s*([0-9.]+)s\]\s?")
VERDICT_RE = re.compile(r"\[verdict\] \S+ -> (\{.*\})\s*$")
SOLVE_RE = re.compile(r"\[solve\] (\{.*\})\s*$")
ANSWER_RE = re.compile(r"\[answer\] pct=(\S+)")
REFRESH_RE = re.compile(r"refresh\.php")
FINAL_RE = re.compile(r"=== SUCCESS validate=(\S+) score=(\S+) ===")


def parse_log(text: str) -> dict:
    events = []  # (t, kind, payload)
    solve_marks = []
    for ln in text.splitlines():
        m = TIME_RE.match(ln)
        t = float(m.group(1)) if m else None
        body = TIME_RE.sub("", ln).strip()
        vm = VERDICT_RE.search(body)
        # the driver prints the same payload twice: "[verdict] ... -> {...}" and then
        # "=== SUCCESS validate=... ===".  Only the bracketed line is an event; counting
        # both inflates attempts and hides first-try successes.
        if vm and t is not None and body.startswith("[verdict]"):
            payload = json.loads(vm.group(1))
            data = payload.get("data") or {}
            result = data.get("result") if isinstance(data, dict) else None
            events.append((t, "verdict", {"result": result,
                                          "validate": data.get("validate"),
                                          "score": data.get("score")}))
        elif REFRESH_RE.search(body) and "req" in body:
            events.append((t, "refresh", {}))
        sm = SOLVE_RE.search(body)
        if sm:
            s = json.loads(sm.group(1))
            solve_marks.append({"t": t, "ms": s.get("solve_ms"), "prompt": s.get("prompt"),
                                "n": s.get("n"), "pic": s.get("pic"),
                                "candidates": s.get("candidates"),
                                "fallback": sum(1 for m in (s.get("matches") or []) if m.get("fallback")),
                                "points": s.get("points")})
        am = ANSWER_RE.search(body)
        if am and t is not None:
            events.append((t, "answer", {"pct": am.group(1)}))

    verdicts = [e for e in events if e[1] == "verdict"]
    fails = [v for v in verdicts if v[2]["result"] == "fail"]
    succs = [v for v in verdicts if v[2]["result"] == "success"]
    all_verdicts = [v[2]["result"] for v in verdicts]
    # 'click' is the pre-check that selects the product, not an answer attempt
    m = FINAL_RE.search(text)
    return {
        "verdicts": all_verdicts,
        "n_attempts": sum(1 for v in all_verdicts if v in ("success", "fail")),
        "n_fail": len(fails),
        "first_try": bool(all_verdicts and all_verdicts[0] == "success"),
        "refreshes": sum(1 for e in events if e[1] == "refresh"),
        "solves": solve_marks,
        "final_validate": m.group(1) if m else None,
        "final_score": m.group(2) if m else None,
    }


def main() -> int:
    dirs = sys.argv[1:] or ["bench_logs"]
    files = []
    for d in dirs:
        files += sorted(glob.glob(str(TASK / d / "round_*.log")))
    rows = []
    for f in files:
        try:
            text = pathlib.Path(f).read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        r = parse_log(text)
        r["file"] = pathlib.Path(f).name
        rows.append(r)

    if not rows:
        print("no logs found")
        return 1

    n = len(rows)
    first_try = sum(1 for r in rows if r["first_try"])
    with_retry = sum(1 for r in rows if r["n_attempts"] > 1)
    solved = sum(1 for r in rows if r["final_validate"])
    total_attempts = sum(r["n_attempts"] for r in rows)

    print(f"rounds analysed        : {n}")
    print(f"final success          : {solved}/{n} = {solved/n*100:.1f}%")
    print(f"first-attempt success  : {first_try}/{n} = {first_try/n*100:.1f}%")
    print(f"rounds needing retry   : {with_retry}/{n} = {with_retry/n*100:.1f}%")
    print(f"total answer attempts  : {total_attempts} (mean {total_attempts/n:.2f}/round)")
    dist: dict[int, int] = {}
    for r in rows:
        dist[r["n_attempts"]] = dist.get(r["n_attempts"], 0) + 1
    print(f"attempts distribution  : " + ", ".join(f"{k} attempts x{v}" for k, v in sorted(dist.items())))
    print(f"challenge refreshes    : {sum(r['refreshes'] for r in rows)}")
    print(f"solver invocations     : {sum(len(r['solves']) for r in rows)}")

    print("\nper round:")
    for r in rows:
        print(f"  {r['file']:<16} attempts={r['n_attempts']} "
              f"verdicts={r['verdicts']} solves={len(r['solves'])} "
              f"prompts={[s['prompt'] for s in r['solves']]}")

    ms = [s["ms"] for r in rows for s in r["solves"] if s["ms"]]
    if ms:
        ms_sorted = sorted(ms)
        print(f"\nsolve_ms (per invocation, n={len(ms)}): min={ms_sorted[0]} "
              f"median={int(statistics.median(ms_sorted))} mean={int(sum(ms)/len(ms))} max={ms_sorted[-1]}")
    fb = [s["fallback"] for r in rows for s in r["solves"]]
    if fb:
        print(f"fallback assignments/solve: mean={sum(fb)/len(fb):.2f} max={max(fb)} "
              f"({sum(1 for x in fb if x)}/{len(fb)} solves had >=1 fallback)")

    scores = {r["final_score"] for r in rows if r["final_score"]}
    print(f"final scores           : {sorted(scores)}")
    (TASK / "bench_analysis.json").write_text(json.dumps(rows, ensure_ascii=True, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

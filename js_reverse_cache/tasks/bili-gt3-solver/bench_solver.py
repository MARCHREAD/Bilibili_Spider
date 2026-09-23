"""Accuracy + speed benchmark for the browser-free GT3 (bilibili word-click) solver.

Runs N fresh rounds end to end through gt3_protocol.py (the same command main.py
assembles), keeps the full stderr trace of every round, and reports:

  * accuracy  : successes / rounds, with the server's own /ajax.php verdict
  * speed     : wall time per round (total), plus the phases parsed from the trace
                (initial SDK `w` -> round image -> local solve -> final submit -> verdict)
  * solver    : in-process solve_ms reported by the protocol driver
  * uniqueness: the validate codes must all differ (proves rounds are not replayed)

usage:
    python bench_solver.py --rounds 10
    python bench_solver.py --rounds 20 --jobs 3     # parallel workers
    python bench_solver.py --rounds 8 --keep-logs
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import pathlib
import re
import statistics
import subprocess
import sys
import time

TASK = pathlib.Path(__file__).resolve().parent
LOGDIR = TASK / "bench_logs"

SUCCESS_RE = re.compile(r"=== SUCCESS validate=(\S+) score=(\S+) ===")
VERDICT_RE = re.compile(r"\[verdict\] \S+ -> (\{.*\})\s*$", re.M)
SOLVE_RE = re.compile(r"\[solve\] (\{.*\})\s*$", re.M)
TIME_RE = re.compile(r"\[t\+\s*([0-9.]+)s\]")
HTTP_RE = re.compile(r"http used: (\d+)")
ROUND_RE = re.compile(r"\[round (?:top|data)\] (\{.*\})\s*$", re.M)
PROMPT_RE = re.compile(r"\[prompt\] (\S+) n=(\d+)")


def clean_trace(raw: str) -> str:
    """Drop the [t+..s] prefix so the log matches what main.py already parses."""
    return "\n".join(TIME_RE.sub("", ln).rstrip() for ln in raw.splitlines())


def parse_round(no: int, proc: subprocess.CompletedProcess, seconds: float) -> dict:
    raw = (proc.stdout or "") + "\n" + (proc.stderr or "")
    out = clean_trace(raw)

    m = SUCCESS_RE.search(out)
    verdicts = VERDICT_RE.findall(out)
    solves = [json.loads(s) for s in SOLVE_RE.findall(out)]

    # phase marks from the timestamped trace, in the order the driver printed them
    marks = [(float(t), ln) for t, ln in
             ((TIME_RE.match(ln).group(1), ln) for ln in raw.splitlines() if TIME_RE.match(ln))]
    phases: dict[str, float] = {}
    for ts, ln in marks:
        body = TIME_RE.sub("", ln).strip()
        if body.startswith("[round] gt="):
            phases.setdefault("t_challenge", ts)
        elif body.startswith("[helper] ready"):
            phases.setdefault("t_sdk_ready", ts)
        elif body.startswith("[verdict]"):
            phases["t_verdict"] = ts
        elif body.startswith("[solver]"):
            phases["t_solved"] = ts

    res = {
        "round": no,
        "ok": bool(m),
        "validate": m.group(1) if m else None,
        "score": m.group(2) if m else None,
        "verdict": json.loads(verdicts[-1]) if verdicts else None,
        "http_used": int(HTTP_RE.search(out).group(1)) if HTTP_RE.search(out) else None,
        "seconds": round(seconds, 2),
        "returncode": proc.returncode,
    }
    if solves:
        s = solves[-1]
        res["solve_ms"] = s.get("solve_ms")
        res["prompt"] = s.get("prompt")
        res["n_clicks"] = s.get("n")
        res["points"] = s.get("points")
        res["pic"] = s.get("pic")
    pr = PROMPT_RE.search(out)
    if pr:
        res.setdefault("prompt", pr.group(1))
        res.setdefault("n_clicks", int(pr.group(2)))

    res["phases"] = {k: round(v, 2) for k, v in phases.items()}
    if "t_challenge" in phases and "t_sdk_ready" in phases:
        res["sdk_setup_s"] = round(phases["t_sdk_ready"] - phases["t_challenge"], 2)
    if "t_verdict" in phases and "t_solved" in phases:
        res["submit_s"] = round(phases["t_verdict"] - phases["t_solved"], 2)
    res["log"] = raw
    if not res["ok"]:
        res["tail"] = [TIME_RE.sub("", ln).strip()[:200] for ln in raw.splitlines()
                       if "[verdict]" in ln or "SUCCESS" in ln or "[warn]" in ln][-4:]
    return res


def run_round(no: int, max_http: int, timeout: int) -> dict:
    cmd = [
        sys.executable, str(TASK / "gt3_protocol.py"),
        "--max-http", str(max_http),
        "--patched-core", "--patched-click",
        "--call-widget", "$_BJJQ",
        "--answer-format", "pct",
        "--verify-first",
        "--timer-cap", "2000",
        "--helper-rounds", "80",
    ]
    started = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=str(TASK), capture_output=True, text=True,
                              timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        proc = subprocess.CompletedProcess(cmd, -1, exc.stdout or "", exc.stderr or "")
    return parse_round(no, proc, time.perf_counter() - started)


def stats(values: list[float]) -> dict:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return {}
    return {
        "n": len(vals),
        "min": round(vals[0], 2),
        "median": round(statistics.median(vals), 2),
        "mean": round(sum(vals) / len(vals), 2),
        "max": round(vals[-1], 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=1, help="parallel rounds (default 1 = honest serial timing)")
    ap.add_argument("--max-http", type=int, default=20)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--keep-logs", action="store_true")
    ap.add_argument("--logdir", default=None,
                    help="where to write per-round traces (default bench_logs/<label>, "
                         "label derived from the report name so runs never overwrite each other)")
    ap.add_argument("--out", default="bench_report.json")
    args = ap.parse_args()

    logdir = pathlib.Path(args.logdir) if args.logdir else (
        LOGDIR / pathlib.Path(args.out).stem)
    if args.keep_logs:
        logdir.mkdir(parents=True, exist_ok=True)
    print(f"GT3 benchmark: {args.rounds} fresh round(s), jobs={args.jobs}", flush=True)
    started = time.perf_counter()
    results: list[dict] = []

    if args.jobs <= 1:
        for i in range(1, args.rounds + 1):
            r = run_round(i, args.max_http, args.timeout)
            results.append(r)
            tag = "OK  " if r["ok"] else "FAIL"
            print(f"  [{i:>2}/{args.rounds}] {tag} {r['seconds']:>6.2f}s "
                  f"solve={r.get('solve_ms')}ms http={r['http_used']} "
                  f"n={r.get('n_clicks')} prompt={r.get('prompt')} "
                  f"validate={r.get('validate')}", flush=True)
            for ln in r.get("tail") or []:
                print(f"        {ln}", flush=True)
    else:
        with futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futs = {pool.submit(run_round, i, args.max_http, args.timeout): i
                    for i in range(1, args.rounds + 1)}
            done = 0
            for fut in futures.as_completed(futs):
                r = fut.result()
                results.append(r)
                done += 1
                tag = "OK  " if r["ok"] else "FAIL"
                print(f"  [{done:>2}/{args.rounds}] {tag} {r['seconds']:>6.2f}s "
                      f"solve={r.get('solve_ms')}ms validate={r.get('validate')}", flush=True)

    wall = time.perf_counter() - started
    results.sort(key=lambda r: r["round"])
    ok = [r for r in results if r["ok"]]
    validates = [r["validate"] for r in ok]

    summary = {
        "rounds": args.rounds,
        "jobs": args.jobs,
        "successes": len(ok),
        "accuracy": round(len(ok) / args.rounds, 4),
        "wall_seconds": round(wall, 1),
        "per_round_seconds": stats([r["seconds"] for r in results]),
        "solver_ms": stats([r.get("solve_ms") for r in results]),
        "submit_s": stats([r.get("submit_s") for r in results]),
        "sdk_setup_s": stats([r.get("sdk_setup_s") for r in results]),
        "http_used": stats([r["http_used"] for r in results]),
        "scores": sorted({r["score"] for r in ok if r["score"]}),
        "validate_unique": len(set(validates)) == len(validates),
        "validates": validates,
        "prompts": [r.get("prompt") for r in results],
        "results": [{k: v for k, v in r.items() if k != "log"} for r in results],
    }
    (TASK / args.out).write_text(json.dumps(summary, ensure_ascii=True, indent=2), encoding="utf-8")

    for r in results:
        if args.keep_logs:
            (logdir / f"round_{r['round']:02d}.log").write_text(r["log"], encoding="utf-8", errors="replace")

    print("\n==== benchmark ====")
    print(f"accuracy    : {len(ok)}/{args.rounds} = {summary['accuracy'] * 100:.1f}%")
    print(f"wall        : {summary['wall_seconds']}s total")
    for name in ("per_round_seconds", "solver_ms", "submit_s", "sdk_setup_s", "http_used"):
        s = summary[name]
        if s:
            unit = "ms" if name.endswith("_ms") else ("s" if name.endswith("_s") or name == "per_round_seconds" else "")
            print(f"{name:<16}: min={s['min']}{unit} median={s['median']}{unit} "
                  f"mean={s['mean']}{unit} max={s['max']}{unit}")
    print(f"scores      : {summary['scores']}")
    print(f"unique valid: {summary['validate_unique']}")
    print(f"detail      : {args.out}" + (f", logs in {logdir}/" if args.keep_logs else ""))
    return 0 if len(ok) == args.rounds else 1


if __name__ == "__main__":
    raise SystemExit(main())

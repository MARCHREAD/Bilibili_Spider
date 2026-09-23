"""Show the solve-by-solve story of chosen benchmark rounds: prompt, match, verdict.

usage: python show_round.py round_04 round_08        # reads bench_logs/<name>.log
       python show_round.py --all
"""
from __future__ import annotations

import glob
import json
import pathlib
import re
import sys

TIME = re.compile(r"\[t\+\s*([0-9.]+)s\]\s?")
TASK = pathlib.Path(__file__).resolve().parent


def show(path: pathlib.Path) -> None:
    print("=" * 72)
    print(path.name)
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = TIME.match(ln)
        t = m.group(1) if m else "  ?  "
        b = TIME.sub("", ln).strip()
        if b.startswith("[solve]"):
            s = json.loads(b[7:])
            print(f"  t+{t}s SOLVE pic={s['pic']} n={s['n']} solve_ms={s['solve_ms']}")
            print(f"          prompt_ocr={s['prompt']}")
            print(f"          card_candidates={s['candidates']}")
            print(f"          card_readings={s['readings']}")
            print(f"          boxes={s['field_boxes']}")
            pts = [(m2["prompt_char"], m2["best_char"], m2["score"], m2["fallback"],
                    m2["x"], m2["y"]) for m2 in s["matches"]]
            for i, p in enumerate(pts):
                print(f"          #{i} prompt={p[0]!r} -> best={p[1]!r} score={p[2]} "
                      f"fallback={p[3]} at ({p[4]},{p[5]})")
        elif b.startswith("[answer]"):
            print(f"  t+{t}s {b[:100]}")
        elif b.startswith("[verdict]"):
            print(f"  t+{t}s VERDICT {b.split('-> ')[-1][:110]}")
        elif b.startswith("=== SUCCESS"):
            print(f"  t+{t}s {b}")


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] == "--all":
        files = sorted(glob.glob(str(TASK / "bench_logs" / "round_*.log")))
    else:
        files = [str(TASK / "bench_logs" / f"{a}.log") for a in args]
    for f in files:
        p = pathlib.Path(f)
        if p.exists():
            show(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

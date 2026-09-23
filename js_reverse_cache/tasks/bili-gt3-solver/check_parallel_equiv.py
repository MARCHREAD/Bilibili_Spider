"""Equivalence + speed: pooled OCR vs serial OCR, on every labelled round image.

Proves the thread-pool optimisation is behaviour-preserving (byte-identical readings,
same click points) and measures the wall-clock win on real images.

usage: python check_parallel_equiv.py [extra.jpg ...]
"""
from __future__ import annotations

import concurrent.futures as futures
import glob
import json
import os
import pathlib
import sys
import time

import gt3_click_solve_v11 as v11

TASK = pathlib.Path(__file__).resolve().parent
DEFAULT_WORKERS = max(1, min(8, os.cpu_count() or 1))
CHECK_KEYS = ("prompt_chars", "n_clicks", "click_points", "field_boxes",
              "matches", "prompt_candidates", "candidate_lengths",
              "prompt_readings", "scores")


def reset_pool(workers: int) -> None:
    """workers=0 means 'the module default'; 1 means serial."""
    if v11._OCR_POOL is not None:
        v11._OCR_POOL.shutdown(wait=True)
    v11._OCR_POOL = None
    v11.OCR_WORKERS = workers or DEFAULT_WORKERS


def run(pic: pathlib.Path, workers: int) -> tuple[dict, float]:
    reset_pool(workers)
    t = time.perf_counter()
    res = v11.solve(pic)
    return res, time.perf_counter() - t


CACHE_PATH = TASK / "parallel_equiv_cache.json"


def load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def cached_or_run(cache: dict, pic: pathlib.Path, mode: str, workers: int,
                  force: bool) -> tuple[dict, float]:
    """Serial runs are minutes long; keep them across invocations unless --force."""
    try:
        rel = str(pic.relative_to(TASK))
    except ValueError:
        rel = pic.name
    key = f"{rel}:{mode}"
    if not force and key in cache:
        entry = cache[key]
        return entry["res"], entry["seconds"]
    res, seconds = run(pic, workers)
    cache[key] = {"res": res, "seconds": round(seconds, 3)}
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=True), encoding="utf-8")
    return res, seconds


def main() -> int:
    force = "--force" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    pics = sorted(glob.glob(str(TASK / "cache" / "live*.jpg")))
    pics += sorted(glob.glob(str(TASK / "cache" / "proto_*" / "pic_*.jpg")))[-6:]
    pics += [str(pathlib.Path(p)) for p in args]
    seen, ordered = set(), []
    for p in pics:
        if p not in seen and pathlib.Path(p).exists():
            seen.add(p)
            ordered.append(pathlib.Path(p))

    cache = load_cache()
    print(f"{len(ordered)} image(s); pooled workers={DEFAULT_WORKERS}"
          f" (env GT3_OCR_WORKERS overrides); force={force}")
    all_same, rows = True, []
    for pic in ordered:
        serial, t_serial = cached_or_run(cache, pic, "serial", 1, force)
        pooled, t_pooled = cached_or_run(cache, pic, "pooled", 0, force)
        same = all(json.dumps(serial.get(k), sort_keys=True, ensure_ascii=False)
                   == json.dumps(pooled.get(k), sort_keys=True, ensure_ascii=False)
                   for k in CHECK_KEYS)
        all_same &= same
        rows.append({
            "pic": str(pic.relative_to(TASK)),
            "prompt": pooled.get("prompt_chars"),
            "n": pooled.get("n_clicks"),
            "identical": same,
            "serial_s": round(t_serial, 2),
            "pooled_s": round(t_pooled, 2),
            "speedup": round(t_serial / t_pooled, 2) if t_pooled else None,
        })
        flag = "SAME " if same else "DIFF!"
        print(f"  {flag} {pic.name:<22} prompt={pooled.get('prompt_chars')} "
              f"serial={t_serial:6.2f}s pooled={t_pooled:6.2f}s "
              f"speedup={rows[-1]['speedup']}x", flush=True)
        if not same:
            for k in CHECK_KEYS:
                a = json.dumps(serial.get(k), sort_keys=True, ensure_ascii=False)
                b = json.dumps(pooled.get(k), sort_keys=True, ensure_ascii=False)
                if a != b:
                    print(f"        {k}:\n          serial={a[:300]}\n          pooled={b[:300]}")

    sp = [r["speedup"] for r in rows if r["speedup"]]
    print(f"\nidentical on all {len(rows)} image(s): {all_same}")
    if sp:
        print(f"speedup: min={min(sp)}x median={sorted(sp)[len(sp)//2]}x max={max(sp)}x")
    (TASK / "parallel_equiv.json").write_text(json.dumps(rows, ensure_ascii=True, indent=2), encoding="utf-8")
    return 0 if all_same else 1


if __name__ == "__main__":
    raise SystemExit(main())

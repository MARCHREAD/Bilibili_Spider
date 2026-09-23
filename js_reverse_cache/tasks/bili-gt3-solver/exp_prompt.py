"""Experiment: how many characters does the prompt ask for, and can ddddocr read
them?  Also check what v8's chamfer pipeline picks when topk is raised.
"""
from __future__ import annotations

import json
import pathlib
import sys

import cv2
import numpy as np

import gt3_click_solve_v8 as v8
from gt3_click_solve import find_prompt_box
from gt3_click_solve_dd import det_boxes, field_mask, prompt_mask

TASK = pathlib.Path(__file__).resolve().parent
PIC = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else TASK / "cache" / "proto_20260921-200053" / "pic_7.jpg"


def column_groups(mask: np.ndarray, gap: int = 3) -> list[tuple[int, int]]:
    cols = (mask > 0).sum(axis=0) > 0
    groups: list[tuple[int, int]] = []
    start = None
    run = 0
    for i, on in enumerate(cols):
        if on:
            if start is None:
                start = i
            run = 0
        elif start is not None:
            run += 1
            if run > gap:
                groups.append((start, i - run))
                start = None
                run = 0
    if start is not None:
        groups.append((start, len(cols) - 1))
    return groups


def main() -> int:
    img = cv2.imdecode(np.fromfile(str(PIC), dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    px, py, pw, ph = find_prompt_box(img)
    print(f"[box] prompt=({px},{py},{pw},{ph}) img={w}x{h}")

    strip = img[py:py + ph, px:px + pw]
    out_png = TASK / "cache" / "prompt_strip.png"
    cv2.imencode(".png", strip)[1].tofile(str(out_png))
    print(f"[save] {out_png}")

    for tipw in (pw, 116, 200):
        sub = img[py:py + ph, px:px + min(pw, tipw)]
        m = prompt_mask(sub)
        groups = column_groups(m)
        print(f"[seg tipw={tipw}] ink={int((m > 0).sum())} groups={len(groups)} -> {groups}")

    import ddddocr
    det = ddddocr.DdddOcr(det=True, show_ad=False)
    rec = ddddocr.DdddOcr(show_ad=False)
    for scale in (1, 2, 3, 4):
        big = cv2.resize(strip, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        ok, buf = cv2.imencode(".png", big)
        try:
            txt = rec.classification(buf.tobytes())
        except Exception as exc:  # noqa: BLE001
            txt = f"err:{exc}"
        print(f"[ocr x{scale}] {txt!r}")

    field = img[:py, :]
    boxes = [b for b in det_boxes(det, field) if b[2] >= 15 and b[3] >= 15]
    print(f"[field] {len(boxes)} boxes: {boxes}")
    for (x, y, bw, bh) in boxes:
        crop = field[max(0, y - 2):y + bh + 2, max(0, x - 2):x + bw + 2]
        big = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        ok, buf = cv2.imencode(".png", big)
        try:
            t = rec.classification(buf.tobytes())
        except Exception as exc:  # noqa: BLE001
            t = f"err:{exc}"
        print(f"   box=({x},{y},{bw},{bh}) -> {t!r}")

    print("\n[v8 topk=3]")
    import subprocess
    r = subprocess.run([sys.executable, str(TASK / "gt3_click_solve_v8.py"), str(PIC), "--topk", "3"],
                       capture_output=True, text=True, cwd=str(TASK))
    print(r.stdout[-1500:])
    print(r.stderr[-2000:])
    return 0


if __name__ == "__main__":
    sys.exit(main())

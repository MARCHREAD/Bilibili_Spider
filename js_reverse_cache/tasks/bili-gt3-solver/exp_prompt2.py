"""Prompt-strip analysis, ASCII-safe output: mask profile, character segmentation
and ddddocr readings (prompt + each field glyph).
"""
from __future__ import annotations

import json
import pathlib
import sys

import cv2
import numpy as np

from gt3_click_solve import find_prompt_box
from gt3_click_solve_dd import det_boxes, prompt_mask

TASK = pathlib.Path(__file__).resolve().parent
PIC = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else TASK / "cache" / "proto_20260921-200053" / "pic_7.jpg"
OUT = TASK / "cache" / "prompt_probe.json"


def groups_from(mask: np.ndarray, gap: int) -> list[list[int]]:
    cols = (mask > 0).sum(axis=0) > 0
    out, start, run = [], None, 0
    for i, on in enumerate(cols):
        if on:
            if start is None:
                start = i
            run = 0
        elif start is not None:
            run += 1
            if run > gap:
                out.append([start, i - run])
                start, run = None, 0
    if start is not None:
        out.append([start, len(cols) - 1])
    return out


def main() -> int:
    img = cv2.imdecode(np.fromfile(str(PIC), dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    px, py, pw, ph = find_prompt_box(img)
    strip = img[py:py + ph, px:px + pw]
    cv2.imencode(".png", strip)[1].tofile(str(TASK / "cache" / "prompt_strip.png"))
    mask = prompt_mask(strip)
    cols = (mask > 0).sum(axis=0)
    rows = (mask > 0).sum(axis=1)

    import ddddocr
    rec = ddddocr.DdddOcr(show_ad=False)
    det = ddddocr.DdddOcr(det=True, show_ad=False)

    rep: dict = {
        "pic": str(PIC), "size": [w, h], "prompt_box": [px, py, pw, ph],
        "strip_shape": list(strip.shape), "ink": int((mask > 0).sum()),
        "col_profile": [int(c) for c in cols],
        "row_span": [int(np.argmax(rows > 0)), int(len(rows) - np.argmax(rows[::-1] > 0) - 1)],
        "groups": {str(g): groups_from(mask, g) for g in (1, 2, 3, 4, 5, 6, 8)},
    }

    ocr = {}
    for scale in (1, 2, 3):
        big = cv2.resize(strip, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        ok, buf = cv2.imencode(".png", big)
        ocr[f"prompt_x{scale}"] = rec.classification(buf.tobytes())
    field = img[:py, :]
    boxes = [b for b in det_boxes(det, field) if b[2] >= 15 and b[3] >= 15]
    glyphs = []
    for (x, y, bw, bh) in boxes:
        crop = field[max(0, y - 2):y + bh + 2, max(0, x - 2):x + bw + 2]
        big = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        ok, buf = cv2.imencode(".png", big)
        glyphs.append({"box": [x, y, bw, bh], "ocr": rec.classification(buf.tobytes())})
    rep["ocr"] = ocr
    rep["glyphs"] = glyphs

    OUT.write_text(json.dumps(rep, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "col_profile"}, ensure_ascii=True, indent=2))
    print("col_profile:", rep["col_profile"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

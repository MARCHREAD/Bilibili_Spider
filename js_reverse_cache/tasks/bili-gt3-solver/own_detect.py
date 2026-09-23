"""Own glyph detector: neon strokes over a photo are compact saturated blobs, and
ddddocr's text detector keeps cutting them short (it returned a 50x49 box for a
~60x60 glyph, which corrupts every downstream mask/metric).

Pipeline: median-background difference -> threshold -> dilate to join the strokes of
one glyph -> connected components -> boxes whose area/scale look like a glyph.
"""
from __future__ import annotations

import json
import pathlib
import sys

import cv2
import numpy as np

from gt3_click_solve_dd import note

TASK = pathlib.Path(__file__).resolve().parent


def stroke_mask(img: np.ndarray, k: int = 21, thr: float | None = None) -> np.ndarray:
    k = k if k % 2 == 1 else k + 1
    med = cv2.medianBlur(img, k)
    d = np.linalg.norm(img.astype(np.float32) - med.astype(np.float32), axis=2)
    if thr is None:
        t, _ = cv2.threshold(d.astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        thr = max(28.0, float(t))
    return ((d > thr).astype(np.uint8) * 255)


def detect_glyphs(field: np.ndarray, dilate: int = 9, min_area: int = 350,
                  max_area: int = 12000) -> tuple[list[tuple[int, int, int, int]], np.ndarray]:
    m = stroke_mask(field)
    joined = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate, dilate)))
    n, lab, stats, cent = cv2.connectedComponentsWithStats(joined, 8)
    boxes = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (min_area <= area <= max_area):
            continue
        if w < 18 or h < 18:
            continue
        if w > field.shape[1] * 0.6 or h > field.shape[0] * 0.6:
            continue
        # trim the dilation back off the box
        pad = dilate // 2
        boxes.append((max(0, x + pad), max(0, y + pad),
                      max(8, w - dilate), max(8, h - dilate)))
    boxes.sort(key=lambda b: (b[1], b[0]))
    return boxes, m


def main() -> int:
    pic = pathlib.Path(sys.argv[1])
    out = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else TASK / "cache" / "own_detect.png"
    img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    field = img[:h - 40, :]
    boxes, m = detect_glyphs(field)
    print("boxes:", boxes)

    tiles = []
    for (x, y, bw, bh) in boxes:
        crop = field[y:y + bh, x:x + bw]
        mm = stroke_mask(crop)
        tiles.append((f"{x},{y}", cv2.resize(mm, (96, 96), interpolation=cv2.INTER_NEAREST)))
    if tiles:
        canvas = np.zeros((96 + 30, 100 * len(tiles), 3), np.uint8)
        for k, (label, t) in enumerate(tiles):
            canvas[0:96, k * 100:k * 100 + 96] = cv2.cvtColor(t, cv2.COLOR_GRAY2BGR)
            cv2.putText(canvas, label, (k * 100, 122), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1)
        cv2.imencode(".png", canvas)[1].tofile(str(out))
        note(f"[montage] {out}")

    vis = field.copy()
    for (x, y, bw, bh) in boxes:
        cv2.rectangle(vis, (x, y), (x + bw, y + bh), (0, 255, 255), 2)
    cv2.imencode(".jpg", vis)[1].tofile(str(TASK / "cache" / "own_detect_boxes.jpg"))
    print(json.dumps({"n": len(boxes)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

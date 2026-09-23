"""k-means glyph mask test.

The glyph is a thin neon drawing in ONE colour family over a photo whose dominant
colour is usually a different family (here a blue/purple outline over an orange sunset).
Global saturation/value thresholds fail; a 2-3 cluster k-means on colour separates the
two populations, and the glyph is the cluster that is thin (high perimeter/area).
"""
from __future__ import annotations

import json
import pathlib
import sys

import cv2
import numpy as np

TASK = pathlib.Path(__file__).resolve().parent


def kmeans_masks(crop: np.ndarray, k: int = 3) -> list[tuple[int, np.ndarray]]:
    z = crop.reshape(-1, 3).astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(z, k, None, crit, 4, cv2.KMEANS_PP_CENTERS)
    out = []
    for i in range(k):
        m = (labels.reshape(crop.shape[:2]) == i).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        out.append((i, m))
    return out


def thinness(m: np.ndarray) -> float:
    """perimeter^2 / area -- high for thin drawings, low for solid blobs."""
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return 0.0
    per = sum(cv2.arcLength(c, True) for c in cnts)
    area = float((m > 0).sum()) or 1.0
    return per * per / area


def main() -> int:
    pic = pathlib.Path(sys.argv[1])
    img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    field = img[:h - 40, :]
    out_png = TASK / "cache" / "kmeans.png"
    tiles = []
    cases = json.loads(sys.argv[2]) if len(sys.argv) > 2 else [["huang", 195, 185], ["bao", 290, 63], ["liang", 280, 157]]
    for name, cx, cy in cases:
        half = 46
        crop = field[max(0, cy - half):cy + half, max(0, cx - half):cx + half]
        masks = kmeans_masks(crop, 3)
        scored = sorted(((thinness(m), i, m) for i, m in masks), reverse=True)
        best_t, best_i, best_m = scored[0]
        print(f"{name}: clusters=" + ", ".join(f"#{i} area={int((m>0).sum())} thin={thinness(m):.1f}" for i, m in masks)
              + f"  -> thin cluster #{best_i}")
        big = cv2.resize(crop, (150, 150))
        tiles.append((name, big))
        for rank, (_t, i, m) in enumerate(scored):
            tiles.append((f"#{i}" + ("*" if rank == 0 else ""), cv2.cvtColor(cv2.resize(m, (150, 150), interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)))
    S = 150
    canvas = np.zeros((S + 26, S * len(tiles), 3), np.uint8)
    for i, (lab, t) in enumerate(tiles):
        canvas[0:S, i * S:i * S + S] = t
        cv2.putText(canvas, lab, (i * S + 3, S + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
    cv2.imwrite(str(out_png), canvas)
    print("saved", out_png)
    return 0


if __name__ == "__main__":
    sys.exit(main())

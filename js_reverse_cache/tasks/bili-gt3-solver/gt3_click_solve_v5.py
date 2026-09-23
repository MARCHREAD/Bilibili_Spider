"""Word-click solver v5: projection prompt split + chamfer shape matching.

Detection: ddddocr's detector is reliable on the big field glyphs (4/4 tight
boxes). The prompt card is small, clean, dark-on-white text, so a column
projection split is more reliable there than the model.

Identification: these glyphs are the SAME font in both places, just rotated,
scaled and recoloured. So match by symmetric chamfer distance over a rotation
sweep -- the descriptor is the stroke geometry itself, not a normalized blob.

usage: python gt3_click_solve_v5.py <pic.jpg> [--out annotated.jpg] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import cv2
import numpy as np

from gt3_click_solve import find_prompt_box
from gt3_click_solve_dd import det_boxes, field_mask, note, prompt_mask

TASK = pathlib.Path(__file__).resolve().parent
WORK = 96          # working resolution for the chamfer comparison


def split_by_projection(mask: np.ndarray, expected: int = 4) -> list[tuple[int, int, int, int]]:
    """Split a clean dark-on-light text row into per-character boxes."""
    cols = (mask > 0).sum(axis=0)
    groups: list[tuple[int, int]] = []
    start = None
    gap = 0
    for x, c in enumerate(cols):
        if c > 0:
            if start is None:
                start = x
            gap = 0
        elif start is not None:
            gap += 1
            if gap > 2:                      # tolerate 2px inter-stroke gaps
                groups.append((start, x - gap))
                start = None
    if start is not None:
        groups.append((start, len(cols) - 1))
    groups = [(a, b) for (a, b) in groups if b - a >= 5]

    # if strokes split a character, merge the closest neighbours until expected
    while len(groups) > expected:
        gaps = [(groups[i + 1][0] - groups[i][1], i) for i in range(len(groups) - 1)]
        gaps.sort()
        _, i = gaps[0]
        groups[i] = (groups[i][0], groups[i + 1][1])
        groups.pop(i + 1)
    boxes = []
    for (a, b) in groups:
        sub = mask[:, a:b + 1]
        rows = np.where((sub > 0).sum(axis=1) > 0)[0]
        if len(rows) == 0:
            continue
        boxes.append((int(a), int(rows.min()), int(b - a + 1), int(rows.max() - rows.min() + 1)))
    return boxes


def fill(mask: np.ndarray, k: int = 5) -> np.ndarray:
    """Close stroke gaps and fill holes: Chinese glyphs are far more separable as
    filled silhouettes than as thin outlines."""
    m = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8), iterations=2)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = np.zeros_like(m)
    cv2.drawContours(out, cnts, -1, 255, thickness=cv2.FILLED)
    return out


def to_work(mask: np.ndarray, size: int = WORK) -> np.ndarray:
    """Fit the ink into a square working canvas, preserving aspect ratio."""
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return np.zeros((size, size), np.uint8)
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    s = (size - 8) / max(crop.shape)
    rs = cv2.resize(crop, (max(1, int(round(crop.shape[1] * s))), max(1, int(round(crop.shape[0] * s)))),
                    interpolation=cv2.INTER_NEAREST)
    canvas = np.zeros((size, size), np.uint8)
    oy, ox = (size - rs.shape[0]) // 2, (size - rs.shape[1]) // 2
    canvas[oy:oy + rs.shape[0], ox:ox + rs.shape[1]] = rs
    return canvas


def rot(mask: np.ndarray, angle: float) -> np.ndarray:
    h, w = mask.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(mask, m, (w, h), flags=cv2.INTER_NEAREST)


def chamfer(a: np.ndarray, b: np.ndarray) -> float:
    """IoU on filled silhouettes dominates (structure), chamfer breaks ties."""
    if a.sum() == 0 or b.sum() == 0:
        return 1e9
    inter = float(np.logical_and(a > 0, b > 0).sum())
    union = float(np.logical_or(a > 0, b > 0).sum()) or 1.0
    iou = inter / union

    def dt(m):
        return cv2.distanceTransform((m == 0).astype(np.uint8), cv2.DIST_L2, 3)

    da, db = dt(a), dt(b)
    fwd = float(da[b > 0].mean())
    bwd = float(db[a > 0].mean())
    cd = 0.5 * (fwd + bwd)
    return (1.0 - iou) * 40.0 + cd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pic")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--expected", type=int, default=4)
    args = ap.parse_args()

    import ddddocr

    pic = pathlib.Path(args.pic)
    img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    det = ddddocr.DdddOcr(det=True, show_ad=False)

    pbox = find_prompt_box(img)
    px, py, pw, ph = pbox
    card = img[py:py + ph, px:px + pw]
    cmask = prompt_mask(card)
    # the prompt glyphs overlap each other, so column projection cannot split
    # them; the detector handles this card well (verified on a live round)
    p_boxes = [b for b in det_boxes(det, card, scale=3.0) if b[2] >= 6 and b[3] >= 10]
    if not p_boxes:
        p_boxes = split_by_projection(cmask, expected=args.expected)

    field = img[:py, :]
    f_boxes = [b for b in det_boxes(det, field) if b[2] >= 15 and b[3] >= 15]

    result: dict = {
        "pic": str(pic), "size": [w, h], "prompt_box": list(pbox),
        "prompt_boxes": [list(b) for b in p_boxes], "field_boxes": [list(b) for b in f_boxes],
    }
    if not p_boxes or not f_boxes:
        result["error"] = "segmentation failed"
        print(json.dumps(result, ensure_ascii=True)[:500])
        return 1

    p_masks = [to_work(fill(cmask[y:y + bh, x:x + bw])) for (x, y, bw, bh) in p_boxes]
    f_masks = [to_work(fill(field_mask(field[y:y + bh, x:x + bw]))) for (x, y, bw, bh) in f_boxes]

    angles = list(range(0, 360, 8))
    dist = np.full((len(p_masks), len(f_masks)), 1e9, np.float32)
    best_angle = {}
    for i, pm in enumerate(p_masks):
        for j, fm in enumerate(f_masks):
            best, ba = 1e9, 0
            for a in angles:
                d = chamfer(rot(pm, a), fm)
                if d < best:
                    best, ba = d, a
            dist[i, j] = best
            best_angle[(i, j)] = ba
    result["distance_matrix"] = [[round(float(v), 3) for v in row] for row in dist]

    used: set[int] = set()
    matches = []
    for i in range(len(p_masks)):
        order = np.argsort(dist[i])
        pick = next((int(j) for j in order if int(j) not in used), None)
        if pick is None:
            continue
        used.add(pick)
        bx, by, bw, bh = f_boxes[pick]
        matches.append({"prompt_index": i, "field_index": pick, "x": bx + bw // 2, "y": by + bh // 2,
                        "distance": round(float(dist[i, pick]), 3), "angle": best_angle[(i, pick)]})
    result["matches"] = matches
    result["click_points"] = [[m["x"], m["y"]] for m in matches]

    note(f"[prompt] {len(p_boxes)} boxes {p_boxes}")
    note(f"[field ] {len(f_boxes)} boxes {f_boxes}")
    note("[dist  ] " + json.dumps(result["distance_matrix"]))
    for m in matches:
        note(f"   prompt#{m['prompt_index']} -> field#{m['field_index']} ({m['x']},{m['y']}) "
             f"dist={m['distance']} angle={m['angle']}")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    if args.out:
        vis = img.copy()
        cv2.rectangle(vis, (px, py), (px + pw, py + ph), (0, 255, 0), 1)
        for i, (x, y, bw, bh) in enumerate(p_boxes):
            cv2.rectangle(vis, (px + x, py + y), (px + x + bw, py + y + bh), (255, 160, 0), 1)
            cv2.putText(vis, str(i + 1), (px + x, py + y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 160, 0), 1)
        for (x, y, bw, bh) in f_boxes:
            cv2.rectangle(vis, (x, y), (x + bw, y + bh), (0, 255, 255), 1)
        for k, m in enumerate(matches, start=1):
            cv2.circle(vis, (m["x"], m["y"]), 16, (0, 0, 255), 2)
            cv2.putText(vis, str(m["prompt_index"] + 1), (m["x"] - 6, m["y"] + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.imencode(".jpg", vis)[1].tofile(str(args.out))
        note(f"[vis] -> {args.out}")

    print(json.dumps({k: v for k, v in result.items() if k != "distance_matrix"}, ensure_ascii=True)[:900])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

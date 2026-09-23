"""Word-click solver for the GT3 point-click ('word') round.

Pipeline (no OCR model, no classification):
  1. prompt strip = bright low-saturation band at the bottom; glyphs are dark
     strokes on white -> Otsu inverse + per-character component split
  2. field glyph candidates = MSER regions filtered by size/aspect/chroma
  3. per-candidate glyph mask = pixels far from the box's median colour
  4. match prompt glyph -> candidate glyph with an angle x scale search
     (same font is used in both, so the SHAPES match; we never read the chars)
  5. unique assignment by best score, emit click points in prompt order

usage: python gt3_click_solve.py <pic.jpg> [--out annotated.jpg] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import cv2
import numpy as np

CANVAS = 64


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


# ---------------------------------------------------------------- prompt ----
def find_prompt_box(img: np.ndarray) -> tuple[int, int, int, int]:
    """Locate the white prompt box at the bottom (bright, low-saturation, large)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    sat, val = hsv[:, :, 1], hsv[:, :, 2]
    h, w = img.shape[:2]
    bright = ((val > 175) & (sat < 70)).astype(np.uint8) * 255
    bright[: int(h * 0.7), :] = 0            # only look at the bottom band
    n, _, stats, _ = cv2.connectedComponentsWithStats(bright, connectivity=8)
    best = None
    for i in range(1, n):
        x, y, bw, bh, area = (int(v) for v in stats[i])
        if area < 800 or bw < w * 0.2 or bh < 15:
            continue
        if best is None or area > best[4]:
            best = (x, y, bw, bh, area)
    if best is None:
        return (0, int(h * 0.88), w, h - int(h * 0.88))
    return best[:4]


def prompt_glyph_boxes(img: np.ndarray, box: tuple[int, int, int, int]) -> tuple[list[tuple[int, int, int, int]], np.ndarray]:
    x, y, w, h = box
    sub = img[y:y + h, x:x + w]
    gray = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    boxes = split_glyphs(mask, min_area=25)
    return boxes, mask


def split_glyphs(mask: np.ndarray, min_area: int) -> list[tuple[int, int, int, int]]:
    """Connected components, then merge only boxes whose gap is tiny (same char)."""
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    boxes = [tuple(int(v) for v in stats[i][:4]) for i in range(1, n) if stats[i][4] >= min_area]
    boxes = [b for b in boxes if b[2] >= 4 and b[3] >= 8]

    def vertical_overlap(a, b) -> bool:
        return not (a[1] + a[3] < b[1] or b[1] + b[3] < a[1])

    def hgap(a, b) -> int:
        return max(b[0] - (a[0] + a[2]), a[0] - (b[0] + b[2]))

    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if vertical_overlap(a, b) and hgap(a, b) <= 2:
                    nx, ny = min(a[0], b[0]), min(a[1], b[1])
                    boxes[i] = (nx, ny, max(a[0] + a[2], b[0] + b[2]) - nx, max(a[1] + a[3], b[1] + b[3]) - ny)
                    boxes.pop(j)
                    merged = True
                    break
            if merged:
                break
    boxes.sort(key=lambda b: b[0])
    return boxes


def normalize(mask: np.ndarray) -> np.ndarray:
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return np.zeros((CANVAS, CANVAS), np.uint8)
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    scale = (CANVAS - 8) / max(crop.shape)
    rs = cv2.resize(crop, (max(1, int(round(crop.shape[1] * scale))), max(1, int(round(crop.shape[0] * scale)))),
                    interpolation=cv2.INTER_NEAREST)
    canvas = np.zeros((CANVAS, CANVAS), np.uint8)
    oy, ox = (CANVAS - rs.shape[0]) // 2, (CANVAS - rs.shape[1]) // 2
    canvas[oy:oy + rs.shape[0], ox:ox + rs.shape[1]] = rs
    return canvas


# ----------------------------------------------------------------- field ----
def field_candidates(field: np.ndarray) -> list[tuple[int, int, int, int]]:
    b, g, r = (field[:, :, i].astype(np.int16) for i in range(3))
    chroma = np.maximum(np.maximum(b, g), r) - np.minimum(np.minimum(b, g), r)
    h, w = field.shape[:2]

    cands: list[tuple[int, int, int, int, float]] = []
    mser = cv2.MSER_create()
    mser.setMinArea(60)
    mser.setMaxArea(24000)
    try:
        _, boxes = mser.detectRegions(field)
    except Exception:  # noqa: BLE001
        boxes = []
    for (x, y, bw, bh) in boxes:
        if bw < 24 or bh < 24 or bw > 140 or bh > 140:
            continue
        if not (0.3 <= bw / float(bh) <= 3.4):
            continue
        sub = chroma[y:y + bh, x:x + bw]
        if float(sub.mean()) < 55:
            continue
        cands.append((int(x), int(y), int(bw), int(bh), float(sub.mean())))

    cands.sort(key=lambda t: -t[4])
    kept: list[tuple[int, int, int, int]] = []
    for (x, y, bw, bh, _s) in cands:
        cx, cy = x + bw / 2, y + bh / 2
        if any(abs(cx - (kx + kw / 2)) < 45 and abs(cy - (ky + kh / 2)) < 45 for (kx, ky, kw, kh) in kept):
            continue
        kept.append((x, y, bw, bh))
    kept.sort(key=lambda b: (b[1] // 60, b[0]))
    return kept


def box_mask(field: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = box
    sub = field[y:y + h, x:x + w].astype(np.float32)
    med = np.median(sub.reshape(-1, 3), axis=0)
    dist = np.linalg.norm(sub - med, axis=2)
    thr = max(45.0, float(np.percentile(dist, 70)))
    mask = (dist > thr).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8), iterations=1)
    return mask


def rotate(img: np.ndarray, angle: float, scale: float) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    out = cv2.warpAffine(img, m, (nw, nh), flags=cv2.INTER_NEAREST)
    return cv2.resize(out, (CANVAS, CANVAS), interpolation=cv2.INTER_NEAREST)


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    inter = float(np.logical_and(a > 0, b > 0).sum())
    union = float(np.logical_or(a > 0, b > 0).sum()) or 1.0
    iou = inter / union
    corr = float(cv2.matchTemplate(a.astype(np.float32), b.astype(np.float32), cv2.TM_CCOEFF_NORMED)[0][0])
    return 0.65 * iou + 0.35 * max(0.0, corr)


def solve(pic_path: pathlib.Path) -> dict:
    img = cv2.imdecode(np.fromfile(str(pic_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"cannot read {pic_path}")
    h, w = img.shape[:2]
    pbox = find_prompt_box(img)
    prompt_boxes, pmask = prompt_glyph_boxes(img, pbox)
    prompt_boxes = [b for b in prompt_boxes if b[2] < pbox[2] * 0.6]
    field_img = img[:pbox[1], :]

    fboxes = field_candidates(field_img)
    result: dict = {
        "pic": str(pic_path), "size": [w, h], "prompt_box": list(pbox),
        "prompt_boxes": [list(b) for b in prompt_boxes], "field_boxes": [list(b) for b in fboxes],
    }
    if not prompt_boxes or not fboxes:
        result["error"] = "segmentation failed"
        return result

    p_tpl = [normalize(pmask[y:y + bh, x:x + bw]) for (x, y, bw, bh) in prompt_boxes]
    f_tpl = [normalize(box_mask(field_img, b)) for b in fboxes]

    angles = list(range(0, 360, 12))
    scales = [1.0]
    score = np.zeros((len(p_tpl), len(f_tpl)), np.float32)
    best_cfg: dict[tuple[int, int], dict] = {}
    for i, pt in enumerate(p_tpl):
        for j, ft in enumerate(f_tpl):
            best = -1.0
            cfg = None
            for a in angles:
                for s in scales:
                    cand = rotate(pt, a, s)
                    v = similarity(cand, ft)
                    if v > best:
                        best, cfg = v, {"angle": a, "scale": s}
            score[i, j] = best
            best_cfg[(i, j)] = cfg or {}

    result["score_matrix"] = [[round(float(v), 4) for v in row] for row in score]

    used: set[int] = set()
    clicks = []
    for i in range(len(p_tpl)):
        order = np.argsort(-score[i])
        pick = next((int(j) for j in order if int(j) not in used), None)
        if pick is None:
            continue
        used.add(pick)
        x, y, bw, bh = fboxes[pick]
        clicks.append({
            "prompt_index": i, "field_index": pick, "x": x + bw // 2, "y": y + bh // 2,
            "score": round(float(score[i, pick]), 4), **best_cfg[(i, pick)],
        })
    result["matches"] = clicks
    result["click_points"] = [[c["x"], c["y"]] for c in clicks]
    return result


def annotate(pic_path: pathlib.Path, result: dict, out_path: pathlib.Path) -> None:
    img = cv2.imdecode(np.fromfile(str(pic_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    pb = result.get("prompt_box") or [0, 0, 0, 0]
    cv2.rectangle(img, (pb[0], pb[1]), (pb[0] + pb[2], pb[1] + pb[3]), (0, 255, 0), 1)
    for i, (x, y, w2, h2) in enumerate(result.get("prompt_boxes", [])):
        cv2.rectangle(img, (pb[0] + x, pb[1] + y), (pb[0] + x + w2, pb[1] + y + h2), (255, 160, 0), 1)
        cv2.putText(img, str(i + 1), (pb[0] + x, pb[1] + y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 160, 0), 1)
    for (x, y, w2, h2) in result.get("field_boxes", []):
        cv2.rectangle(img, (x, y), (x + w2, y + h2), (0, 255, 255), 1)
    for c in result.get("matches", []):
        cv2.circle(img, (c["x"], c["y"]), 15, (0, 0, 255), 2)
        cv2.putText(img, str(c["prompt_index"] + 1), (c["x"] - 6, c["y"] + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    cv2.imencode(".jpg", img)[1].tofile(str(out_path))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pic")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    pic = pathlib.Path(args.pic)
    result = solve(pic)
    note(f"[solve] prompt={len(result.get('prompt_boxes', []))} field={len(result.get('field_boxes', []))} "
         f"points={result.get('click_points')}")
    for c in result.get("matches", []):
        note(f"   prompt#{c['prompt_index']} -> field#{c['field_index']} ({c['x']},{c['y']}) "
             f"angle={c.get('angle')} score={c['score']}")
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    if args.out:
        annotate(pic, result, pathlib.Path(args.out))
        note(f"[solve] annotated -> {args.out}")
    print(json.dumps({k: v for k, v in result.items() if k not in ("matches",)}, ensure_ascii=True)[:1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

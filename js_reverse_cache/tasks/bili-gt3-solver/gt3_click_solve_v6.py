"""Word-click solver v6: compose-and-compare, no prompt segmentation at all.

Why: on the prompt card the glyphs are drawn so tightly that they overlap, so any
per-character crop is contaminated by its neighbours (that is what made the
per-pair matcher flat). Instead we treat the card as ONE target mask and ask:
which ordered selection of field glyphs, pasted into a strip, reproduces it?

  - card mask          : dark ink on the white prompt card (reliable)
  - field glyph masks  : tight detector boxes (reliable)
  - hypothesis         : an ordered k-subset of field glyphs
  - score              : IoU + chamfer between the synthesised strip and the card
  - answer             : the best-scoring hypothesis

usage: python gt3_click_solve_v6.py <pic.jpg> [--out annotated.jpg] [--json out.json]
"""
from __future__ import annotations

import argparse
import itertools
import json
import pathlib
import sys

import cv2
import numpy as np

from gt3_click_solve import find_prompt_box
from gt3_click_solve_dd import det_boxes, field_mask, note, prompt_mask
from gt3_click_solve_v5 import fill

TASK = pathlib.Path(__file__).resolve().parent
STRIP_H = 48          # common working height for both the card and the glyphs


def norm_height(mask: np.ndarray, height: int = STRIP_H) -> np.ndarray:
    """Scale a mask so its ink height equals `height`, preserving aspect."""
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return np.zeros((height, 1), np.uint8)
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    s = height / crop.shape[0]
    w = max(1, int(round(crop.shape[1] * s)))
    return cv2.resize(crop, (w, height), interpolation=cv2.INTER_NEAREST)


def rotate_mask(mask: np.ndarray, angle: float) -> np.ndarray:
    h, w = mask.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos) + 2, int(h * cos + w * sin) + 2
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    out = cv2.warpAffine(mask, m, (nw, nh), flags=cv2.INTER_NEAREST)
    return out


def compose(glyphs: list[np.ndarray], gap: int, height: int = STRIP_H) -> np.ndarray:
    gap = int(gap)
    glyphs = [norm_height(g, height) for g in glyphs]
    total = int(sum(g.shape[1] for g in glyphs) + gap * (len(glyphs) - 1))
    strip = np.zeros((height, max(1, total)), np.uint8)
    x = 0
    for g in glyphs:
        strip[:, x:x + g.shape[1]] = g
        x += g.shape[1] + gap
    return strip


def score(a: np.ndarray, b: np.ndarray) -> float:
    """Compare two strips after normalising width (spacing is not the signal)."""
    w = 220
    A = cv2.resize(a, (w, STRIP_H), interpolation=cv2.INTER_NEAREST)
    B = cv2.resize(b, (w, STRIP_H), interpolation=cv2.INTER_NEAREST)
    inter = float(np.logical_and(A > 0, B > 0).sum())
    union = float(np.logical_or(A > 0, B > 0).sum()) or 1.0
    iou = inter / union
    da = cv2.distanceTransform((A == 0).astype(np.uint8), cv2.DIST_L2, 3)
    db = cv2.distanceTransform((B == 0).astype(np.uint8), cv2.DIST_L2, 3)
    cd = 0.5 * (float(da[B > 0].mean()) + float(db[A > 0].mean()))
    return (1.0 - iou) * 40.0 + cd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pic")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--count", type=int, default=0, help="prompt glyph count (0 = infer)")
    args = ap.parse_args()

    import ddddocr

    pic = pathlib.Path(args.pic)
    img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    det = ddddocr.DdddOcr(det=True, show_ad=False)

    px, py, pw, ph = find_prompt_box(img)
    card_mask = prompt_mask(img[py:py + ph, px:px + pw])
    card_strip = norm_height(fill(card_mask, 3))

    field = img[:py, :]
    f_boxes = [b for b in det_boxes(det, field) if b[2] >= 15 and b[3] >= 15]
    f_masks = [fill(field_mask(field[y:y + bh, x:x + bw]), 5) for (x, y, bw, bh) in f_boxes]

    result = {"pic": str(pic), "size": [w, h], "prompt_box": [px, py, pw, ph],
              "prompt_ink": int((card_mask > 0).sum()), "field_boxes": [list(b) for b in f_boxes]}
    if not f_masks or card_mask.sum() == 0:
        result["error"] = "segmentation failed"
        print(json.dumps(result, ensure_ascii=True)[:400])
        return 1

    # infer how many glyphs the card shows: card ink width / typical glyph width
    glyph_w = np.median([m.shape[1] for m in f_masks])
    k = args.count or max(1, int(round((card_mask.shape[1] * 0.62) / max(1.0, glyph_w))))
    k = min(k, len(f_masks))
    result["prompt_count"] = int(k)

    angles = [0, 15, 345, 30, 330, 60, 300, 90, 270]
    best = None
    cache: dict[tuple[int, int], tuple[float, np.ndarray]] = {}
    for combo in itertools.permutations(range(len(f_masks)), k):
        variants = [cache.get((idx, a)) for idx in combo for a in angles]
        # per-slot best angle, then compose with those
        chosen = []
        for idx in combo:
            best_local = None
            for a in angles:
                key = (idx, a)
                if key not in cache:
                    cache[key] = (a, rotate_mask(f_masks[idx], a))
                rot = cache[key][1]
                strip = compose([rot], gap=0)
                s = score(strip, card_strip)
                if best_local is None or s < best_local[0]:
                    best_local = (s, rot, a)
            chosen.append(best_local)
        strip = compose([c[1] for c in chosen], gap=max(2, glyph_w // 8))
        s = score(strip, card_strip)
        if best is None or s < best["score"]:
            best = {"score": round(float(s), 4), "order": list(combo),
                    "angles": [c[2] for c in chosen]}
    result["best"] = best
    if best:
        matches = []
        for slot, idx in enumerate(best["order"]):
            bx, by, bw, bh = f_boxes[idx]
            matches.append({"prompt_index": slot, "field_index": int(idx),
                            "x": bx + bw // 2, "y": by + bh // 2, "angle": best["angles"][slot]})
        result["matches"] = matches
        result["click_points"] = [[m["x"], m["y"]] for m in matches]

    note(f"[card ] box=({px},{py},{pw},{ph}) ink={result['prompt_ink']} inferred_k={k} glyph_w={glyph_w:.0f}")
    note(f"[field] {len(f_boxes)} boxes {f_boxes}")
    note(f"[best ] score={best['score'] if best else None} order={best['order'] if best else None} angles={best['angles'] if best else None}")
    note(f"[click] {result.get('click_points')}")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    if args.out:
        vis = img.copy()
        cv2.rectangle(vis, (px, py), (px + pw, py + ph), (0, 255, 0), 1)
        for (x, y, bw, bh) in f_boxes:
            cv2.rectangle(vis, (x, y), (x + bw, y + bh), (0, 255, 255), 1)
        for m in result.get("matches", []):
            cv2.circle(vis, (m["x"], m["y"]), 16, (0, 0, 255), 2)
            cv2.putText(vis, str(m["prompt_index"] + 1), (m["x"] - 6, m["y"] + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.imencode(".jpg", vis)[1].tofile(str(args.out))
        note(f"[vis] -> {args.out}")

    print(json.dumps({k2: v for k2, v in result.items() if k2 != "field_boxes"}, ensure_ascii=True)[:700])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

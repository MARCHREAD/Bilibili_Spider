"""Word-click solver v7: slide each field glyph over the whole prompt card.

Both earlier attempts failed for the same reason: the prompt card cannot be
segmented (glyphs overlap), and per-pair comparison of contaminated crops is
flat. So invert it:

  - keep the field glyph masks tight (detector boxes) and stroke-accurate (no fill)
  - keep the card mask as ONE target (dark ink on the white card)
  - slide each field glyph, over a rotation sweep, across the whole card mask
  - a glyph that IS in the prompt finds a sharp best position; a distractor does not
  - the prompt order is simply the matched positions sorted by x

usage: python gt3_click_solve_v7.py <pic.jpg> [--out annotated.jpg] [--json out.json]
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
from gt3_click_solve_v6 import norm_height, rotate_mask

TASK = pathlib.Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pic")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--topk", type=int, default=3)
    args = ap.parse_args()

    import ddddocr

    pic = pathlib.Path(args.pic)
    img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    det = ddddocr.DdddOcr(det=True, show_ad=False)

    px, py, pw, ph = find_prompt_box(img)
    card = prompt_mask(img[py:py + ph, px:px + pw])
    # glyph height inside the card = the card's ink height
    ys = np.where((card > 0).sum(axis=1) > 0)[0]
    card_h = int(ys.max() - ys.min() + 1) if len(ys) else ph
    card_f = card.astype(np.float32)

    field = img[:py, :]
    f_boxes = [b for b in det_boxes(det, field) if b[2] >= 15 and b[3] >= 15]
    f_masks = [field_mask(field[y:y + bh, x:x + bw]) for (x, y, bw, bh) in f_boxes]

    result = {"pic": str(pic), "size": [w, h], "prompt_box": [px, py, pw, ph],
              "card_h": card_h, "field_boxes": [list(b) for b in f_boxes], "per_glyph": []}
    if not f_masks or card.sum() == 0:
        result["error"] = "segmentation failed"
        print(json.dumps(result, ensure_ascii=True)[:400])
        return 1

    best_per_glyph = []
    for idx, gm in enumerate(f_masks):
        tpl0 = norm_height(gm, card_h)
        best = None
        for angle in range(0, 360, 10):
            tpl = rotate_mask(tpl0, angle) if angle else tpl0
            tpl = norm_height(tpl, card_h)
            th, tw = tpl.shape
            if th >= card.shape[0] or tw >= card.shape[1]:
                pad = np.zeros((max(th, card.shape[0] + 2), max(tw, card.shape[1] + 2)), np.uint8)
                pad[:card.shape[0], :card.shape[1]] = card
                res = cv2.matchTemplate(pad.astype(np.float32), tpl.astype(np.float32), cv2.TM_CCOEFF_NORMED)
            else:
                res = cv2.matchTemplate(card_f, tpl.astype(np.float32), cv2.TM_CCOEFF_NORMED)
            _, mx, _, ml = cv2.minMaxLoc(res)
            if best is None or mx > best["score"]:
                best = {"score": round(float(mx), 4), "angle": angle, "x": int(ml[0]), "y": int(ml[1]),
                        "w": int(tw), "h": int(th)}
        best["field_index"] = idx
        best["field_box"] = list(f_boxes[idx])
        best_per_glyph.append(best)
        note(f"[glyph {idx}] box={f_boxes[idx]} best score={best['score']} angle={best['angle']} at x={best['x']}")

    ranked = sorted(best_per_glyph, key=lambda g: -g["score"])
    chosen = ranked[: args.topk]
    chosen.sort(key=lambda g: g["x"])          # prompt reads left to right
    result["per_glyph"] = best_per_glyph
    result["chosen_order"] = [g["field_index"] for g in chosen]
    matches = []
    for slot, g in enumerate(chosen):
        bx, by, bw, bh = f_boxes[g["field_index"]]
        matches.append({"prompt_index": slot, "field_index": g["field_index"], "match_score": g["score"],
                        "angle": g["angle"], "card_x": g["x"], "x": bx + bw // 2, "y": by + bh // 2})
    result["matches"] = matches
    result["click_points"] = [[m["x"], m["y"]] for m in matches]

    note(f"[rank  ] {[(g['field_index'], g['score']) for g in ranked]}")
    note(f"[order ] field indices = {result['chosen_order']} -> clicks {result['click_points']}")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    if args.out:
        vis = img.copy()
        cv2.rectangle(vis, (px, py), (px + pw, py + ph), (0, 255, 0), 1)
        for (x, y, bw, bh) in f_boxes:
            cv2.rectangle(vis, (x, y), (x + bw, y + bh), (0, 255, 255), 1)
        for m in matches:
            cv2.circle(vis, (m["x"], m["y"]), 16, (0, 0, 255), 2)
            cv2.putText(vis, str(m["prompt_index"] + 1), (m["x"] - 6, m["y"] + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.imencode(".jpg", vis)[1].tofile(str(args.out))
        note(f"[vis] -> {args.out}")

    print(json.dumps({k: v for k, v in result.items() if k not in ("per_glyph",)}, ensure_ascii=True)[:800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

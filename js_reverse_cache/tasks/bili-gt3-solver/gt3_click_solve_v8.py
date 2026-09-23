"""Word-click solver v8: chamfer matching normalised by the glyph's own ink.

v7 used TM_CCOEFF_NORMED against the prompt mask, which is dominated by how much
ink a glyph has: on a labelled real round the densest glyph (a distractor) won.
Here the score is the MEAN closeness of a glyph's own ink pixels to the prompt
ink, so a small thin glyph is judged on its shape, not its mass.

Pipeline:
  1. prompt = the bottom-left window the SDK actually shows (background-size maps
     it ~1:1 with the source image), so the prompt mask is clean
  2. field glyphs = ddddocr detector boxes
  3. score(field glyph, angle) = best mean closeness over a slide across the prompt
  4. prompt order = order of the matched x positions on the prompt

usage: python gt3_click_solve_v8.py <pic.jpg> --topk 2 [--out annotated.jpg]
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
TIP_W = 116          # the .geetest_tip_img window width the SDK shows
SIGMA = 3.0


def closeness(dt: np.ndarray) -> np.ndarray:
    """High near ink; used as the correlation target for chamfer matching."""
    return np.exp(-dt / SIGMA).astype(np.float32)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pic")
    ap.add_argument("--topk", type=int, default=2)
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--tipw", type=int, default=TIP_W)
    args = ap.parse_args()

    import ddddocr

    pic = pathlib.Path(args.pic)
    img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    det = ddddocr.DdddOcr(det=True, show_ad=False)

    px, py, pw, ph = find_prompt_box(img)
    tip = img[py:py + ph, px:px + min(pw, args.tipw)]
    tip_mask = prompt_mask(tip)
    dt = cv2.distanceTransform((tip_mask == 0).astype(np.uint8), cv2.DIST_L2, 3)
    close = closeness(dt)

    ys = np.where((tip_mask > 0).sum(axis=1) > 0)[0]
    tip_h = int(ys.max() - ys.min() + 1) if len(ys) else ph

    field = img[:py, :]
    f_boxes = [b for b in det_boxes(det, field) if b[2] >= 15 and b[3] >= 15]
    f_masks = [field_mask(field[y:y + bh, x:x + bw]) for (x, y, bw, bh) in f_boxes]

    result = {"pic": str(pic), "size": [w, h], "prompt_box": [px, py, pw, ph], "tip_h": tip_h,
              "tip_ink": int((tip_mask > 0).sum()), "field_boxes": [list(b) for b in f_boxes], "per_glyph": []}
    if not f_masks or tip_mask.sum() == 0:
        result["error"] = "segmentation failed"
        print(json.dumps(result, ensure_ascii=True)[:400])
        return 1

    entries = []
    for idx, gm in enumerate(f_masks):
        tpl0 = norm_height(gm, tip_h)
        best = None
        for angle in range(0, 360, 10):
            tpl = norm_height(rotate_mask(tpl0, angle), tip_h) if angle else tpl0
            th, tw = tpl.shape
            ink = float((tpl > 0).sum()) or 1.0
            if th >= close.shape[0] or tw >= close.shape[1]:
                pad = np.zeros((max(th, close.shape[0]), max(tw, close.shape[1])), np.float32)
                pad[:close.shape[0], :close.shape[1]] = close
                res = cv2.matchTemplate(pad, tpl.astype(np.float32), cv2.TM_CCORR)
            else:
                res = cv2.matchTemplate(close, tpl.astype(np.float32), cv2.TM_CCORR)
            _, mx, _, ml = cv2.minMaxLoc(res)
            mean_close = float(mx) / ink
            if best is None or mean_close > best["score"]:
                best = {"score": round(mean_close, 4), "angle": angle, "x": int(ml[0]), "y": int(ml[1]),
                        "w": int(tw), "h": int(th)}
        best["field_index"] = idx
        best["field_box"] = list(f_boxes[idx])
        entries.append(best)
        note(f"[glyph {idx}] box={f_boxes[idx]} score={best['score']} angle={best['angle']} prompt_x={best['x']}")

    ranked = sorted(entries, key=lambda g: -g["score"])
    chosen = ranked[: args.topk]
    chosen.sort(key=lambda g: g["x"])           # prompt reads left to right
    result["per_glyph"] = entries
    result["ranked"] = [(g["field_index"], g["score"]) for g in ranked]
    result["chosen_order"] = [g["field_index"] for g in chosen]

    matches = []
    for slot, g in enumerate(chosen):
        bx, by, bw, bh = f_boxes[g["field_index"]]
        matches.append({"prompt_index": slot, "field_index": g["field_index"], "score": g["score"],
                        "angle": g["angle"], "prompt_x": g["x"], "x": bx + bw // 2, "y": by + bh // 2})
    result["matches"] = matches
    result["click_points"] = [[m["x"], m["y"]] for m in matches]

    note(f"[ranked] {result['ranked']}")
    note(f"[order ] {result['chosen_order']} -> clicks {result['click_points']}")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    if args.out:
        vis = img.copy()
        cv2.rectangle(vis, (px, py), (px + pw, py + ph), (0, 255, 0), 1)
        cv2.rectangle(vis, (px, py), (px + args.tipw, py + ph), (255, 0, 255), 1)
        for (x, y, bw, bh) in f_boxes:
            cv2.rectangle(vis, (x, y), (x + bw, y + bh), (0, 255, 255), 1)
        for m in matches:
            cv2.circle(vis, (m["x"], m["y"]), 16, (0, 0, 255), 2)
            cv2.putText(vis, str(m["prompt_index"] + 1), (m["x"] - 6, m["y"] + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.imencode(".jpg", vis)[1].tofile(str(args.out))
        note(f"[vis] -> {args.out}")

    print(json.dumps({k: v for k, v in result.items() if k not in ("per_glyph",)}, ensure_ascii=True)[:700])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

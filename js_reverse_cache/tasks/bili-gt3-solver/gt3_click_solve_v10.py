"""Word-click solver v10: deterministic prompt card + joint OCR/shape assignment.

Two fixes over v9
-----------------
1. The prompt card is NOT found by inspection anymore.  The SDK always renders it in
   .geetest_tip_img (116x40 CSS px) showing the bottom-left corner of the round image
   at 1:1 (background-size 298% 968%, background-position 0% 100%), i.e. the last 40
   rows and the first 116 columns of the JPEG.  The old heuristic sometimes landed on
   a bright patch of the photo (it returned y=323 instead of 344) and the prompt was
   then read from the wrong pixels.
2. Prompt characters are read jointly with the field glyphs.  Single-shot OCR of the
   card is not always right (爆炒田鸡 came back as 爆炒田鸿), but the answer must be
   among the field glyphs -- so each prompt cell keeps every reading it produced and
   the assignment prefers a reading that some unused glyph was also read as, with the
   rotation/scale IoU of the masks breaking ties and covering unreadable glyphs.

usage: python gt3_click_solve_v10.py <pic.jpg> [--out vis.jpg] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import cv2
import numpy as np

from gt3_click_solve import find_prompt_box
from gt3_click_solve_dd import det_boxes, note
from gt3_click_solve_v6 import norm_height, rotate_mask
from mask_v2 import field_mask_v2, prompt_mask_v2

TASK = pathlib.Path(__file__).resolve().parent
GLYPH_H = 48
ANGLES = list(range(0, 360, 10))
SCALES = (0.9, 1.0, 1.1)
MIN_ANGLE_HITS = 2
CARD_W, CARD_H = 116, 40


def is_cjk(ch: str) -> bool:
    return len(ch) == 1 and "\u4e00" <= ch <= "\u9fff"


def rotate_img(img: np.ndarray, angle: float) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos) + 2, int(h * cos + w * sin) + 2
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(img, m, (nw, nh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def ocr(rec, img: np.ndarray, scale: int = 3) -> str:
    big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC) if scale != 1 else img
    ok, enc = cv2.imencode(".png", big)
    return rec.classification(enc.tobytes()) if ok else ""


def prompt_card(img: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int], str]:
    """Deterministic card; falls back to the heuristic only if the corner is not card-like."""
    h, w = img.shape[:2]
    if h > CARD_H + 8 and w > CARD_W + 8:
        card = img[h - CARD_H:h, 0:CARD_W]
        if float(cv2.cvtColor(card, cv2.COLOR_BGR2GRAY).mean()) > 170:
            return card, (0, h - CARD_H, CARD_W, CARD_H), "fixed"
    px, py, pw, ph = find_prompt_box(img)
    return img[py:py + ph, px:px + min(pw, 200)], (px, py, pw, ph), "heuristic"


def split_cells(mask: np.ndarray, n: int) -> list[np.ndarray]:
    cols = np.where((mask > 0).sum(axis=0) > 0)[0]
    rows = np.where((mask > 0).sum(axis=1) > 0)[0]
    if len(cols) == 0 or len(rows) == 0:
        return []
    x0, x1 = int(cols.min()), int(cols.max()) + 1
    y0, y1 = int(rows.min()), int(rows.max()) + 1
    step = (x1 - x0) / float(n)
    out = []
    for i in range(n):
        a = int(round(x0 + i * step))
        b = int(round(x0 + (i + 1) * step))
        out.append(mask[y0:y1, max(a, 0):max(b, a + 1)])
    return out


def iou_best(pm: np.ndarray, fm: np.ndarray) -> tuple[float, int]:
    tb = (norm_height(fm, GLYPH_H) > 0).astype(np.float32)
    b_ink = float(tb.sum()) or 1.0
    base = norm_height(pm, GLYPH_H)
    best, best_angle = 0.0, 0
    for angle in ANGLES:
        rot = rotate_mask(base, angle) if angle else base
        for s in SCALES:
            tpl = cv2.resize(rot, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST) if s != 1.0 else rot
            a_ink = float((tpl > 0).sum()) or 1.0
            ph, pw = max(tpl.shape[0], tb.shape[0]), max(tpl.shape[1], tb.shape[1])
            pad = np.zeros((ph, pw), np.float32)
            pad[:tb.shape[0], :tb.shape[1]] = tb
            res = cv2.matchTemplate(pad, tpl.astype(np.float32), cv2.TM_CCORR)
            inter = float(res.max()) / 255.0
            v = inter / (a_ink + b_ink - inter)
            if v > best:
                best, best_angle = v, angle
    return best, best_angle


def solve(pic_path: pathlib.Path) -> dict:
    import ddddocr

    img = cv2.imdecode(np.fromfile(str(pic_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"cannot read {pic_path}")
    h, w = img.shape[:2]
    det = ddddocr.DdddOcr(det=True, show_ad=False)
    rec = ddddocr.DdddOcr(show_ad=False)

    card, box, card_src = prompt_card(img)
    px, py, pw, ph = box
    field = img[:py, :]

    # ---- prompt cells + every reading they produce -------------------------
    whole = [ocr(rec, card, s) for s in (2, 3, 6)]
    p_boxes = sorted([b for b in det_boxes(det, card, scale=3.0) if b[2] >= 6 and b[3] >= 10],
                     key=lambda b: b[0])
    card_mask = prompt_mask_v2(card, inset=1)
    cells, n_src = [], "detector"
    if p_boxes:
        cells = [(x, y, bw, bh) for (x, y, bw, bh) in p_boxes]
    texts = [[c for c in t if is_cjk(c)] for t in whole]
    n_text = max((len(t) for t in texts), default=0)
    if not cells or (n_text and len(cells) != n_text):
        if 2 <= n_text <= 6:
            cells, n_src = [], "text-split"
            cols = np.where((card_mask > 0).sum(axis=0) > 0)[0]
            rows = np.where((card_mask > 0).sum(axis=1) > 0)[0]
            if len(cols) and len(rows):
                x0, x1 = int(cols.min()), int(cols.max()) + 1
                y0, y1 = int(rows.min()), int(rows.max()) + 1
                step = (x1 - x0) / float(n_text)
                for i in range(n_text):
                    a = int(round(x0 + i * step)); b = int(round(x0 + (i + 1) * step))
                    cells.append((a, y0, max(1, b - a), y1 - y0))

    p_masks, candidates = [], []
    for i, (x, y, bw, bh) in enumerate(cells):
        crop = card[max(0, y - 1):y + bh + 1, max(0, x - 1):x + bw + 1]
        p_masks.append(prompt_mask_v2(crop, inset=0))
        cand: list[str] = []
        for s in (3, 4):
            t = ocr(rec, crop, s)
            if is_cjk(t):
                cand.append(t)
        if len(texts[0]) == len(cells) if n_src == "detector" else False:
            pass
        for t in texts:
            if len(t) == len(cells) and is_cjk(t[i]):
                cand.append(t[i])
        seen, uniq = set(), []
        for c in cand:
            if c not in seen:
                seen.add(c); uniq.append(c)
        candidates.append(uniq)

    # ---- field glyphs + their de-rotated readings --------------------------
    f_boxes = [b for b in det_boxes(det, field) if b[2] >= 15 and b[3] >= 15]
    f_crops = [field[y:y + bh, x:x + bw] for (x, y, bw, bh) in f_boxes]
    f_masks = [field_mask_v2(c) for c in f_crops]
    readings = []
    for crop in f_crops:
        seen: dict[str, list[int]] = {}
        for angle in ANGLES:
            ch = ocr(rec, rotate_img(crop, angle) if angle else crop)
            if is_cjk(ch):
                seen.setdefault(ch, []).append(angle)
        readings.append(seen)

    iou = [[0.0] * len(f_masks) for _ in range(len(p_masks))]
    iou_angle = [[0] * len(f_masks) for _ in range(len(p_masks))]
    for i, pm in enumerate(p_masks):
        for j, fm in enumerate(f_masks):
            v, a = iou_best(pm, fm)
            iou[i][j] = round(v, 4)
            iou_angle[i][j] = a

    res: dict = {"pic": str(pic_path), "size": [w, h], "prompt_box": list(box),
                 "prompt_card_source": card_src, "prompt_text": whole,
                 "prompt_cells": [list(c) for c in cells], "prompt_cell_source": n_src,
                 "prompt_candidates": candidates, "n_clicks": len(cells),
                 "field_boxes": [list(b) for b in f_boxes], "solver": "v10"}
    if not cells or not f_masks:
        res["error"] = "detection failed"
        return res

    # ---- joint assignment --------------------------------------------------
    used: set[int] = set()
    clicks = []
    for i in range(len(cells)):
        best = None
        for j in range(len(f_masks)):
            if j in used or not f_masks[j].any():
                continue
            hit = next((c for c in candidates[i]
                        if len(readings[j].get(c, [])) >= MIN_ANGLE_HITS), None)
            # a glyph may be readable as a char at fewer angles but still match
            if hit is None:
                hit = next((c for c in candidates[i] if c in readings[j]), None)
            strong = 1 if hit else 0
            key = (strong, iou[i][j])
            if best is None or key > best[0]:
                best = (key, j, hit)
        if best is None:
            continue
        _key, pick, hit = best
        used.add(pick)
        bx, by, bw, bh = f_boxes[pick]
        clicks.append({"prompt_index": i, "prompt_candidates": candidates[i],
                       "matched_char": hit, "field_index": pick,
                       "field_readings": sorted(readings[pick], key=lambda k: -len(readings[pick][k]))[:5],
                       "x": bx + bw // 2, "y": by + bh // 2,
                       "iou": iou[i][pick], "angle": iou_angle[i][pick],
                       "via": "ocr" if hit else "iou"})

    res.update({"readings": readings, "iou_matrix": iou, "matches": clicks,
                "click_points": [[c["x"], c["y"]] for c in clicks]})
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pic")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    res = solve(pathlib.Path(args.pic))
    if res.get("error"):
        print(json.dumps(res, ensure_ascii=True)[:500])
        return 1
    note(f"[card ] {res['prompt_card_source']} box={res['prompt_box']} text={res['prompt_text']}")
    note(f"[cells] {res['n_clicks']} via {res['prompt_cell_source']} boxes={res['prompt_cells']}")
    note(f"[cands] {res['prompt_candidates']}")
    for j, r in enumerate(res["readings"]):
        top = sorted(r, key=lambda k: -len(r[k]))[:4]
        note(f"   glyph{j} {res['field_boxes'][j]} " + " ".join(f"{k!r}x{len(r[k])}" for k in top))
    for c in res["matches"]:
        note(f"   #{c['prompt_index']} {c['prompt_candidates']} -> field#{c['field_index']} "
             f"as {c['matched_char']!r} ({c['x']},{c['y']}) iou={c['iou']} via={c['via']}")
    note(f"[points] {res['click_points']}")
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(res, ensure_ascii=True, indent=2), encoding="utf-8")
    if args.out:
        img = cv2.imdecode(np.fromfile(str(args.pic), dtype=np.uint8), cv2.IMREAD_COLOR)
        px, py, pw, ph = res["prompt_box"]
        vis = img.copy()
        cv2.rectangle(vis, (px, py), (px + pw, py + ph), (0, 255, 0), 1)
        for (x, y, bw, bh) in res["field_boxes"]:
            cv2.rectangle(vis, (x, y), (x + bw, y + bh), (0, 255, 255), 1)
        for k, c in enumerate(res["matches"], start=1):
            cv2.circle(vis, (c["x"], c["y"]), 16, (0, 0, 255), 2)
            cv2.putText(vis, str(k), (c["x"] - 6, c["y"] + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.imencode(".jpg", vis)[1].tofile(str(args.out))
        note(f"[vis] -> {args.out}")
    print(json.dumps({k: v for k, v in res.items() if k not in ("iou_matrix", "readings")},
                     ensure_ascii=True)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Word-click solver v9: identify field glyphs by de-rotated OCR, not by shape score.

Why v9 exists
-------------
v8 scored every field glyph against the whole prompt strip, used the position of its
best slide as the click order, and only ever clicked a hard-coded `topk` glyphs.  On a
real 3-character prompt (炸茄盒) all four glyphs slid to nearly the same x -- the order
was noise, and a 3-character prompt could never be answered.

What the server actually validates: the prompt is an ordered sequence of characters,
so the answer is exactly that many clicks, in prompt order.

How v9 identifies a glyph
-------------------------
ddddocr's RECOGNISER fails on a rotated neon glyph but succeeds once the glyph is
de-rotated: on a real round the true glyph for each prompt character was read at
3-13 of the 36 tested angles, while the blue distractor glyph was unreadable.  So:

  1. the prompt card is read as text  -> the characters AND the click count
  2. every field glyph is re-OCR'd over 0..350 degrees -> a set of readings
  3. prompt char i takes the unused glyph that was read as exactly that character at
     two or more angles (a single accidental reading is not enough)
  4. ties / unreadable glyphs fall back to IoU of the two masks over rotation+scale

usage: python gt3_click_solve_v9.py <pic.jpg> [--out vis.jpg] [--json out.json]
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
GLYPH_H = 48
ANGLES = list(range(0, 360, 10))
SCALES = (0.85, 1.0, 1.18)
MIN_ANGLE_HITS = 2          # a real de-rotated reading repeats across neighbouring angles
MAX_PROMPT = 6


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
    big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    ok, enc = cv2.imencode(".png", big)
    return rec.classification(enc.tobytes()) if ok else ""


def iou_score(p_mask: np.ndarray, f_mask: np.ndarray) -> tuple[float, int]:
    target = norm_height(f_mask, GLYPH_H)
    tb = (target > 0).astype(np.float32)
    b_ink = float(tb.sum()) or 1.0
    base = norm_height(p_mask, GLYPH_H)
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


def split_cells(mask: np.ndarray, n: int) -> list[np.ndarray]:
    """Split a prompt card mask into `n` equal cells across its ink span."""
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


def solve(pic_path: pathlib.Path) -> dict:
    import ddddocr

    img = cv2.imdecode(np.fromfile(str(pic_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"cannot read {pic_path}")
    h, w = img.shape[:2]
    det = ddddocr.DdddOcr(det=True, show_ad=False)
    rec = ddddocr.DdddOcr(show_ad=False)

    px, py, pw, ph = find_prompt_box(img)
    card = img[py:py + ph, px:px + min(pw, 200)]

    # ---- how many clicks, and which characters -----------------------------
    text_ocr = ocr(rec, card)
    text_chars = [c for c in text_ocr if is_cjk(c)]
    p_boxes = sorted([b for b in det_boxes(det, card, scale=3.0) if b[2] >= 6 and b[3] >= 10],
                     key=lambda b: b[0])
    card_mask = prompt_mask(card)
    p_crops, p_masks, p_chars = [], [], []
    if 2 <= len(text_chars) <= MAX_PROMPT and len(p_boxes) != len(text_chars):
        # recogniser read the whole phrase but the detector merged/split boxes:
        # trust the text and cut the ink span into one cell per character
        cells = split_cells(card_mask, len(text_chars))
        zy = np.where((card_mask > 0).sum(axis=1) > 0)[0]
        y0 = int(zy.min()) if len(zy) else 0
        for cell, ch in zip(cells, text_chars):
            p_masks.append(cell)
            p_chars.append(ch)
        p_source = "text-split"
    else:
        for (x, y, bw, bh) in p_boxes:
            p_crops.append(card[y:y + bh, x:x + bw])
        p_masks = [prompt_mask(c) for c in p_crops]
        p_chars = [ocr(rec, c) for c in p_crops]
        if len(text_chars) == len(p_chars):
            p_chars = text_chars          # phrase reading is the more reliable one
        p_source = "detector"

    field = img[:py, :]
    f_boxes = [b for b in det_boxes(det, field) if b[2] >= 15 and b[3] >= 15]
    f_crops = [field[y:y + bh, x:x + bw] for (x, y, bw, bh) in f_boxes]
    f_masks = [field_mask(c) for c in f_crops]

    res: dict = {"pic": str(pic_path), "size": [w, h], "prompt_box": [px, py, pw, ph],
                 "prompt_boxes": [list(b) for b in p_boxes], "prompt_text": text_ocr,
                 "prompt_chars": p_chars, "prompt_source": p_source,
                 "field_boxes": [list(b) for b in f_boxes], "solver": "v9",
                 "n_clicks": len(p_chars)}
    if not p_chars or not f_masks:
        res["error"] = "detection failed"
        return res

    # ---- read every glyph at every rotation --------------------------------
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
            v, a = iou_score(pm, fm)
            iou[i][j] = round(v, 4)
            iou_angle[i][j] = a

    used: set[int] = set()
    clicks = []
    for i, ch in enumerate(p_chars):
        cands = [j for j in range(len(f_masks))
                 if j not in used and len(readings[j].get(ch, [])) >= MIN_ANGLE_HITS]
        if len(cands) == 1:
            pick, how = cands[0], "ocr"
        elif cands:
            pick, how = max(cands, key=lambda j: iou[i][j]), "ocr+iou"
        else:
            free = [j for j in range(len(f_masks)) if j not in used]
            pick, how = (max(free, key=lambda j: iou[i][j]) if free else None), "iou"
        if pick is None:
            continue
        used.add(pick)
        bx, by, bw, bh = f_boxes[pick]
        clicks.append({
            "prompt_index": i, "prompt_char": ch, "field_index": pick,
            "field_readings": sorted(readings[pick], key=lambda k: -len(readings[pick][k]))[:6],
            "field_match_angles": readings[pick].get(ch, []),
            "x": bx + bw // 2, "y": by + bh // 2,
            "iou": iou[i][pick], "angle": iou_angle[i][pick], "picked_by": how,
        })

    res.update({"readings": [{k: v for k, v in r.items()} for r in readings],
                "iou_matrix": iou, "matches": clicks,
                "click_points": [[c["x"], c["y"]] for c in clicks]})
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pic")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    pic = pathlib.Path(args.pic)
    res = solve(pic)
    if res.get("error"):
        print(json.dumps(res, ensure_ascii=True)[:500])
        return 1

    note(f"[prompt] text={res['prompt_text']!r} chars={res['prompt_chars']} via={res['prompt_source']}")
    note(f"[field ] {len(res['field_boxes'])} glyphs")
    for j, r in enumerate(res["readings"]):
        top = sorted(r, key=lambda k: -len(r[k]))[:4]
        note(f"   glyph{j} {res['field_boxes'][j]} readings=" +
             " ".join(f"{k!r}x{len(r[k])}" for k in top))
    for c in res["matches"]:
        note(f"   #{c['prompt_index']} '{c['prompt_char']}' -> field#{c['field_index']} "
             f"({c['x']},{c['y']}) angles={c['field_match_angles']} iou={c['iou']} via={c['picked_by']}")
    note(f"[points] {res['click_points']}")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(res, ensure_ascii=True, indent=2), encoding="utf-8")
    if args.out:
        img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
        px, py, pw, ph = res["prompt_box"]
        vis = img.copy()
        cv2.rectangle(vis, (px, py), (px + pw, py + ph), (0, 255, 0), 1)
        for (x, y, bw, bh) in res["field_boxes"]:
            cv2.rectangle(vis, (x, y), (x + bw, y + bh), (0, 255, 255), 1)
        for k, c in enumerate(res["matches"], start=1):
            cv2.circle(vis, (c["x"], c["y"]), 16, (0, 0, 255), 2)
            cv2.putText(vis, str(k), (c["x"] - 6, c["y"] + 5), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (0, 0, 255), 2)
        cv2.imencode(".jpg", vis)[1].tofile(str(args.out))
        note(f"[vis] -> {args.out}")

    print(json.dumps({k: v for k, v in res.items() if k not in ("iou_matrix", "readings")},
                     ensure_ascii=True)[:700])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

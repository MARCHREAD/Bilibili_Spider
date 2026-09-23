"""Word-click solver: ddddocr detector boxes + rotation/scale shape matching.

Detection is the part OCR models are genuinely good at; identification of these
stylised, rotated glyphs is not (the classifier misreads them). So:
  - ddddocr det gives tight boxes in BOTH the prompt strip and the field
  - prompt glyph mask = dark ink on the white prompt card (clean)
  - field glyph mask  = pixels far from the box's median colour (clean inside a box)
  - identification = angle x scale shape search between the two tight crops
  - ddddocr classification runs as a cross-check, never as the decision

usage: python gt3_click_solve_dd.py <pic.jpg> [--out annotated.jpg] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import cv2
import numpy as np

from gt3_click_solve import find_prompt_box, normalize, rotate, similarity

TASK = pathlib.Path(__file__).resolve().parent


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


def det_boxes(det, img: np.ndarray, scale: float = 1.0) -> list[tuple[int, int, int, int]]:
    """Detector boxes in original-image coordinates; `img` is what the model sees."""
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    ok, enc = cv2.imencode(".png", img)
    if not ok:
        return []
    boxes = []
    for (x1, y1, x2, y2) in det.detection(enc.tobytes()):
        boxes.append((int(x1 / scale), int(y1 / scale), int((x2 - x1) / scale), int((y2 - y1) / scale)))
    boxes.sort(key=lambda b: (b[1] // 40, b[0]))
    return boxes


def prompt_mask(sub: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))


def field_mask(sub: np.ndarray) -> np.ndarray:
    f = sub.astype(np.float32)
    med = np.median(f.reshape(-1, 3), axis=0)
    dist = np.linalg.norm(f - med, axis=2)
    thr = max(40.0, float(np.percentile(dist, 65)))
    mask = (dist > thr).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
    return mask


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pic")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    import ddddocr

    pic = pathlib.Path(args.pic)
    img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    ocr = ddddocr.DdddOcr(show_ad=False)
    det = ddddocr.DdddOcr(det=True, show_ad=False)

    pbox = find_prompt_box(img)
    px, py, pw, ph = pbox

    # --- prompt glyphs: run the detector on an upscaled prompt card ---------
    card = img[py:py + ph, px:px + pw]
    p_boxes = det_boxes(det, card, scale=3.0)
    p_boxes = [b for b in p_boxes if b[2] >= 6 and b[3] >= 10]
    p_crops = [(card[y:y + bh, x:x + bw], (x, y, bw, bh)) for (x, y, bw, bh) in p_boxes]

    # --- field glyphs ------------------------------------------------------
    field = img[:py, :]
    f_boxes = det_boxes(det, field)
    f_boxes = [b for b in f_boxes if b[2] >= 15 and b[3] >= 15]
    f_crops = [(field[y:y + bh, x:x + bw], (x, y, bw, bh)) for (x, y, bw, bh) in f_boxes]

    result: dict = {
        "pic": str(pic), "size": [w, h], "prompt_box": list(pbox),
        "prompt_boxes": [list(b) for (_c, b) in p_crops],
        "field_boxes": [list(b) for (_c, b) in f_crops],
    }
    if not p_crops or not f_crops:
        result["error"] = "detection failed"
        print(json.dumps(result, ensure_ascii=True)[:600])
        return 1

    def read(crop: np.ndarray) -> str:
        big = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        ok, enc = cv2.imencode(".png", big)
        return ocr.classification(enc.tobytes()) if ok else ""

    p_masks = [normalize(prompt_mask(c)) for (c, _b) in p_crops]
    f_masks = [normalize(field_mask(c)) for (c, _b) in f_crops]
    p_chars = [read(c) for (c, _b) in p_crops]
    f_chars = [read(c) for (c, _b) in f_crops]
    result["prompt_chars"] = p_chars
    result["field_chars"] = f_chars

    angles = list(range(0, 360, 10))
    score = np.zeros((len(p_masks), len(f_masks)), np.float32)
    cfg: dict[tuple[int, int], dict] = {}
    for i, pm in enumerate(p_masks):
        for j, fm in enumerate(f_masks):
            best, best_c = -1.0, None
            for a in angles:
                v = similarity(rotate(pm, a, 1.0), fm)
                if v > best:
                    best, best_c = v, {"angle": a}
            score[i, j] = best
            cfg[(i, j)] = best_c or {}
    result["score_matrix"] = [[round(float(v), 4) for v in row] for row in score]

    used: set[int] = set()
    clicks = []
    for i in range(len(p_masks)):
        order = np.argsort(-score[i])
        pick = next((int(j) for j in order if int(j) not in used), None)
        if pick is None:
            continue
        used.add(pick)
        bx, by, bw, bh = f_boxes[pick]
        clicks.append({
            "prompt_index": i, "prompt_char": p_chars[i], "field_index": pick, "field_char": f_chars[pick],
            "x": bx + bw // 2, "y": by + bh // 2, "score": round(float(score[i, pick]), 4),
            **cfg[(i, pick)],
        })
    result["matches"] = clicks
    result["click_points"] = [[c["x"], c["y"]] for c in clicks]

    note(f"[prompt] {len(p_crops)} glyphs chars={p_chars}")
    note(f"[field ] {len(f_crops)} glyphs chars={f_chars}")
    note(f"[match ] points={result['click_points']}")
    for c in clicks:
        note(f"   prompt#{c['prompt_index']} '{c['prompt_char']}' -> field#{c['field_index']} '{c['field_char']}' "
             f"({c['x']},{c['y']}) angle={c['angle']} score={c['score']}")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    if args.out:
        vis = img.copy()
        cv2.rectangle(vis, (px, py), (px + pw, py + ph), (0, 255, 0), 1)
        for (x, y, bw, bh) in [b for (_c, b) in p_crops]:
            cv2.rectangle(vis, (px + x, py + y), (px + x + bw, py + y + bh), (255, 160, 0), 1)
        for (x, y, bw, bh) in f_boxes:
            cv2.rectangle(vis, (x, y), (x + bw, y + bh), (0, 255, 255), 1)
        for k, c in enumerate(clicks, start=1):
            cv2.circle(vis, (c["x"], c["y"]), 15, (0, 0, 255), 2)
            cv2.putText(vis, str(k), (c["x"] - 6, c["y"] + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.imencode(".jpg", vis)[1].tofile(str(args.out))
        note(f"[vis] -> {args.out}")

    print(json.dumps({k: v for k, v in result.items() if k not in ("score_matrix",)}, ensure_ascii=True)[:1000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

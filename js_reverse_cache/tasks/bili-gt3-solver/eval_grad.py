"""Gradient-NCC matching: compare glyphs as dense gradient-magnitude images instead of
binary masks.

Binary masks kept failing for a structural reason: the prompt glyph is a small (33px)
black glyph that thresholds into a fat blob, while the field glyph is a ~65px neon
outline whose mask is thin strokes over a textured photo.  Gradient magnitude is
comparable for both: |d/dx| and |d/dy| peak on the same outlines regardless of colour,
stroke fill or scale.

usage: python eval_grad.py <pic.jpg> [--centres "x,y;x,y;..."]
"""
from __future__ import annotations

import json
import pathlib
import sys

import cv2
import numpy as np

from gt3_click_solve_v10 import is_cjk, ocr, prompt_card
from gt3_click_solve_v6 import norm_height

TASK = pathlib.Path(__file__).resolve().parent
H = 72
ANG = list(range(0, 360, 5))
SCALES = (0.85, 0.95, 1.05, 1.15)


def grad_img(bgr: np.ndarray, height: int = H) -> np.ndarray:
    """Rotation-normalisable gradient magnitude, scaled to a common height.

    Deliberately NO support-cropping: thresholding on mag.max() collapsed some field
    crops to a 1x1 constant (which makes TM_CCOEFF_NORMED return 1.0 for everything).
    """
    if bgr.ndim == 3:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = bgr
    if gray.shape[0] < 4 or gray.shape[1] < 4:
        return np.zeros((height, height), np.float32)
    g = cv2.GaussianBlur(gray, (3, 3), 0)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    s = height / float(gray.shape[0])
    return cv2.resize(mag, (max(4, int(round(gray.shape[1] * s))), height),
                      interpolation=cv2.INTER_AREA).astype(np.float32)


def rotate_f(img: np.ndarray, angle: float) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos) + 2, int(h * cos + w * sin) + 2
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(img, m, (nw, nh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def ncc(pm: np.ndarray, fm: np.ndarray) -> tuple[float, int, float]:
    tgt = fm.astype(np.float32)
    if tgt.std() < 1e-6 or pm.std() < 1e-6:
        return -1.0, 0, 1.0
    pad = max(pm.shape) + 8
    canvas = np.zeros((tgt.shape[0] + 2 * pad, tgt.shape[1] + 2 * pad), np.float32)
    canvas[pad:pad + tgt.shape[0], pad:pad + tgt.shape[1]] = tgt
    best, best_a, best_s = -1.0, 0, 1.0
    for a in ANG:
        rot = rotate_f(pm, a) if a else pm
        for s in SCALES:
            t = cv2.resize(rot, None, fx=s, fy=s, interpolation=cv2.INTER_LINEAR) if s != 1.0 else rot
            if t.shape[0] >= canvas.shape[0] or t.shape[1] >= canvas.shape[1]:
                continue
            if t.std() < 1e-6:
                continue
            res = cv2.matchTemplate(canvas, t, cv2.TM_CCOEFF_NORMED)
            v = float(res.max())
            if v > best:
                best, best_a, best_s = v, a, s
    return best, best_a, best_s


def main() -> int:
    pic = pathlib.Path(sys.argv[1])
    centres = None
    if "--centres" in sys.argv:
        centres = [tuple(int(v) for v in c.split(",")) for c in sys.argv[sys.argv.index("--centres") + 1].split(";")]
    import ddddocr
    img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
    rec = ddddocr.DdddOcr(show_ad=False)
    card, box, src = prompt_card(img)
    field = img[:box[1], :]
    texts = [ocr(rec, card, s) for s in (2, 3, 4, 6)]
    chars = [c for c in max(texts, key=len) if is_cjk(c)]
    n = len(chars)

    # prompt cells: fixed card geometry, equal division of the ink span
    g = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY)
    cm = (g < 140).astype(np.uint8) * 255
    cm[:1, :] = 0; cm[-1:, :] = 0; cm[:, :1] = 0; cm[:, -1:] = 0
    cols = np.where((cm > 0).sum(axis=0) > 0)[0]
    rows = np.where((cm > 0).sum(axis=1) > 0)[0]
    x0, x1 = int(cols.min()), int(cols.max()) + 1
    y0, y1 = int(rows.min()), int(rows.max()) + 1
    print(f"card={src} text={json.dumps(texts, ensure_ascii=True)} n={n} span=({x0},{y0})-({x1},{y1})")
    p_imgs = []
    for i in range(n):
        a = int(round(x0 + (x1 - x0) * i / n)); b = int(round(x0 + (x1 - x0) * (i + 1) / n))
        cell = card[y0:y1, a:b]
        p_imgs.append(grad_img(cell))
        print(f"  cell{i} x={a}..{b} gradsum={p_imgs[-1].sum():.0f}")

    if centres:
        f_imgs, f_labels = [], []
        for (cx, cy) in centres:
            c = field[max(0, cy - 44):cy + 44, max(0, cx - 44):cx + 44]
            f_imgs.append(grad_img(c)); f_labels.append(f"{cx},{cy}")
    else:
        from gt3_click_solve_dd import det_boxes
        det = ddddocr.DdddOcr(det=True, show_ad=False)
        fb = [b for b in det_boxes(det, field) if b[2] >= 15 and b[3] >= 15]
        mw = int(np.median([b[2] for b in fb])); mh = int(np.median([b[3] for b in fb]))
        f_imgs, f_labels = [], []
        for (x, y, bw, bh) in fb:
            x = max(0, x - (mw - bw) // 2); y = max(0, y - (mh - bh) // 2)
            f_imgs.append(grad_img(field[y:y + max(bh, mh), x:x + max(bw, mw)])); f_labels.append(f"{x},{y}")
    print("field:", f_labels)

    print("\ngradient NCC (higher better):")
    for i in range(n):
        row = [ncc(p_imgs[i], f)[0] for f in f_imgs]
        order = np.argsort(row)[::-1]
        print(f"  P{i} '{chars[i]}' " + "  ".join(f"{v:6.3f}" for v in row)
              + f"   best=F{order[0]} 2nd=F{order[1]} margin={row[order[0]] - row[order[1]]:.3f}")

    tiles = []
    for i, im in enumerate(p_imgs):
        tiles.append((f"P{i}", cv2.normalize(im, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)))
    for j, im in enumerate(f_imgs):
        tiles.append((f"F{j}", cv2.normalize(im, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)))
    cw = max(t[1].shape[1] for t in tiles) + 12
    canvas = np.zeros((H + 34, cw * len(tiles), 3), np.uint8)
    for k, (lab, t) in enumerate(tiles):
        x = k * cw + 6
        canvas[2:2 + t.shape[0], x:x + t.shape[1]] = cv2.cvtColor(t, cv2.COLOR_GRAY2BGR)
        cv2.putText(canvas, lab, (x, H + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    out = TASK / "cache" / "eval_grad.png"
    cv2.imencode(".png", canvas)[1].tofile(str(out))
    print("[montage]", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

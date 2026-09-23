"""Test whether preprocessing crops to dark-ink-on-white improves classifier reads."""
from __future__ import annotations

import pathlib
import sys

import cv2
import numpy as np

from gt3_click_solve import find_prompt_box
from gt3_click_solve_dd import det_boxes, field_mask, prompt_mask


def classify(ocr, img: np.ndarray, scale: int = 4) -> str:
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    ok, enc = cv2.imencode(".png", big)
    return ocr.classification(enc.tobytes()) if ok else ""


def main() -> int:
    import ddddocr

    lines: list[str] = []
    pic = pathlib.Path(sys.argv[1])
    img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
    px, py, pw, ph = find_prompt_box(img)
    det = ddddocr.DdddOcr(det=True, show_ad=False)
    ocr = ddddocr.DdddOcr(show_ad=False)

    field = img[:py, :]
    boxes = [b for b in det_boxes(det, field) if b[2] >= 15 and b[3] >= 15]
    lines.append(f"field boxes: {boxes}")
    for i, (x, y, bw, bh) in enumerate(boxes):
        crop = field[y:y + bh, x:x + bw]
        m = field_mask(crop)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
        reads = {
            "raw": classify(ocr, crop),
            "gray": classify(ocr, cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)),
            "prep": classify(ocr, 255 - m),
        }
        lines.append(f"  glyph{i} box=({x},{y},{bw},{bh}) " + "  ".join(f"{k}={v!r}" for k, v in reads.items()))

    card = img[py:py + ph, px:px + pw]
    cm = prompt_mask(card)
    lines.append("card raw : " + repr(classify(ocr, card, 5)))
    lines.append("card prep: " + repr(classify(ocr, 255 - cm, 5)))

    (pathlib.Path(__file__).resolve().parent / "ocr_prep_out.txt").write_text("\n".join(lines), encoding="utf-8")
    print("wrote ocr_prep_out.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Debug helper: dump crops/masks of a word-click pic so the detector can be chosen by eye."""
from __future__ import annotations

import pathlib
import sys

import cv2
import numpy as np

TASK = pathlib.Path(__file__).resolve().parent


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


def main() -> int:
    pic = pathlib.Path(sys.argv[1])
    img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    out = TASK / "debug_click"
    out.mkdir(exist_ok=True)

    prompt = img[337:h, :]
    field = img[:337, :]
    cv2.imwrite(str(out / "01_prompt_x3.png"), cv2.resize(prompt, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST))
    cv2.imwrite(str(out / "02_field_x2.png"), cv2.resize(field, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))

    hsv = cv2.cvtColor(field, cv2.COLOR_BGR2HSV)
    cv2.imwrite(str(out / "03_field_sat.png"), hsv[:, :, 1])
    cv2.imwrite(str(out / "04_field_hue.png"), hsv[:, :, 0])

    gray = cv2.cvtColor(field, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 200)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=2)
    cv2.imwrite(str(out / "05_field_canny_closed.png"), edges)

    # saturation minus local background: glyphs are more saturated than their neighbourhood
    sat = hsv[:, :, 1].astype(np.float32)
    bg = cv2.blur(sat, (31, 31))
    diff = np.clip(sat - bg, 0, 255).astype(np.uint8)
    _, m = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8), iterations=2)
    cv2.imwrite(str(out / "06_field_satdiff.png"), m)

    # prompt strip
    pg = cv2.cvtColor(prompt, cv2.COLOR_BGR2GRAY)
    _, pm = cv2.threshold(pg, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    cv2.imwrite(str(out / "07_prompt_mask.png"), pm)

    note(f"[debug] wrote crops/masks to {out}")
    for f in sorted(out.glob("*.png")):
        note(f"  {f.name} {f.stat().st_size}B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

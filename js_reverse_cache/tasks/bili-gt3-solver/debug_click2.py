"""Debug 2: edge/gradient based ink candidates for the word-click field."""
from __future__ import annotations

import pathlib
import sys

import cv2
import numpy as np

TASK = pathlib.Path(__file__).resolve().parent


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


def main() -> int:
    img = cv2.imdecode(np.fromfile(sys.argv[1], dtype=np.uint8), cv2.IMREAD_COLOR)
    field = img[:337, :]
    out = TASK / "debug_click"
    out.mkdir(exist_ok=True)

    gray = cv2.cvtColor(field, cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    note(f"[stats] gray mean={gray.mean():.1f} std={gray.std():.1f} mag mean={mag.mean():.1f} max={mag.max():.1f}")
    cv2.imwrite(str(out / "10_sobel_mag_raw.png"), np.clip(mag, 0, 255).astype(np.uint8))
    cv2.imwrite(str(out / "11_sobel_mag_norm.png"), cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8))

    q = float(np.percentile(mag, 97))
    _, m97 = cv2.threshold(mag, q, 255, cv2.THRESH_BINARY)
    m97 = cv2.morphologyEx(m97.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=2)
    cv2.imwrite(str(out / "12_mag_top3pct.png"), m97)

    edges = cv2.Canny(gray, 40, 120)
    note(f"[stats] canny px={int((edges > 0).sum())}")
    cv2.imwrite(str(out / "13_canny_raw.png"), edges)
    cv2.imwrite(str(out / "14_canny_closed.png"),
                cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8), iterations=2))

    for f in sorted(out.glob("1*.png")):
        note(f"  {f.name} {f.stat().st_size}B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

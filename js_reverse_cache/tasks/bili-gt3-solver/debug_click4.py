"""Debug 4: dump the prompt-strip mask and its components."""
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
    h = img.shape[0]
    for py0 in (int(h * 0.88), 337, 340, 348):
        strip = img[py0:h, :]
        gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
        thr, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        boxes = [(int(stats[i][0]), int(stats[i][1]), int(stats[i][2]), int(stats[i][3]), int(stats[i][4]))
                 for i in range(1, n)]
        boxes.sort(key=lambda b: -b[4])
        note(f"[strip y0={py0}] size={strip.shape[:2]} otsu={thr:.0f} comps={n-1} top={boxes[:8]}")
        if py0 in (337, 348):
            out = TASK / "debug_click" / f"30_prompt_mask_{py0}.png"
            out.parent.mkdir(exist_ok=True)
            cv2.imencode(".png", mask)[1].tofile(str(out))
            cv2.imencode(".png", cv2.resize(strip, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))[1].tofile(
                str(TASK / "debug_click" / f"31_prompt_{py0}_x2.png"))
            note(f"   wrote {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

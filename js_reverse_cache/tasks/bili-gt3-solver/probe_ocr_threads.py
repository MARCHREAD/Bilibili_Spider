"""Is ddddocr safe and faster under threads? Measure serial vs pooled OCR latency.

usage: python probe_ocr_threads.py [pic.jpg]
"""
from __future__ import annotations

import concurrent.futures as futures
import os
import pathlib
import sys
import time

import cv2
import numpy as np

import gt3_click_solve_v11 as v11
from gt3_click_solve_v10 import ocr

pic = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "cache/proto_20260922-144032/pic_7.jpg")
img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
h, w = img.shape[:2]
field = img[: h - 40, :]

import ddddocr

det = ddddocr.DdddOcr(det=True, show_ad=False)
boxes = v11.detect_boxes(field, det)
recs = v11.build_recognisers()

# one glyph's worth of real work: every (pad, angle, model, scale) job for glyph0
x, y, bw, bh = boxes[0]
crop = field[max(0, y - 4):y + bh + 4, max(0, x - 4):x + bw + 4]

jobs = []
for pi, pad in enumerate(v11.PADS):
    base = cv2.copyMakeBorder(crop, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    for angle in v11.ANGLES:
        im = v11.rotate_img(base, angle) if angle else base
        for ri, rec in enumerate(recs):
            for si, s in enumerate(v11.SCALES):
                jobs.append((pi, ri, si, im, s))
print(f"glyph0: {len(jobs)} OCR jobs, {os.cpu_count()} logical cores, "
      f"cv2 threads={cv2.getNumThreads()}")

# warm up both models so neither pays lazy init inside the timed loop
for _, ri, _, im, s in jobs[:8]:
    ocr(recs[ri], im, s)

t = time.perf_counter()
serial = [ocr(recs[ri], im, s) for _, ri, _, im, s in jobs]
t_serial = time.perf_counter() - t
print(f"serial : {t_serial:6.2f}s  ({t_serial/len(jobs)*1000:5.1f} ms/call)")

for workers in (4, 8, 16):
    with futures.ThreadPoolExecutor(max_workers=workers) as pool:
        t = time.perf_counter()
        parallel = list(pool.map(lambda j: ocr(recs[j[1]], j[3], j[4]), jobs))
        t_par = time.perf_counter() - t
    same = sorted(serial) == sorted(parallel)
    print(f"threads{workers:>3}: {t_par:6.2f}s  ({t_par/len(jobs)*1000:5.1f} ms/call)  "
          f"speedup={t_serial/t_par:4.2f}x  identical_readings={same}")

# process pool: each worker must build its own recognisers (models are not forkable-picklable)
def _proc_worker(payload):
    return payload

print("note: process-pool path needs per-worker model init (~0.4s/worker)")

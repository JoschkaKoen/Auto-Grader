"""PaddleOCR worker — runs inside paddle_env, called as a subprocess by detect_handwriting.py.

Usage:
    paddle_env/bin/python scaffold/paddle_worker.py <img1.png> [<img2.png> ...]

Prints a JSON array to stdout: one boolean per input image, true if handwriting detected.
"""

from __future__ import annotations

import json
import sys

from paddleocr import PPStructure

engine = PPStructure(layout=True, show_log=False, lang="en")

results: list[bool] = []
for path in sys.argv[1:]:
    import cv2

    img = cv2.imread(path)
    if img is None or img.size == 0:
        results.append(False)
        continue
    regions = engine(img)
    results.append(any(r["type"] == "handwriting" for r in regions))

print(json.dumps(results))

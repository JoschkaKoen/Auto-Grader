#!/usr/bin/env bash
# Install packages needed for scripts/ocr_name_benchmark.py into an existing paddle_env.
# Safe to run multiple times (idempotent).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && git rev-parse --show-toplevel)"
PY="${REPO_ROOT}/paddle_env/bin/python"

if [[ ! -x "${PY}" ]]; then
  echo "paddle_env not found at ${REPO_ROOT}/paddle_env"
  echo "Create it with:  bash scripts/install_paddleocr.sh"
  exit 1
fi

echo "Installing ocr_name_benchmark dependencies into paddle_env..."
"${PY}" -m pip install \
  "rich>=13.7.0" \
  "pymupdf>=1.24.0" \
  "pytesseract>=0.3.13" \
  "openpyxl>=3.1.0" \
  "opencv-python-headless>=4.9.0" \
  "Pillow>=10.0.0"

"${PY}" - <<'PY'
import rich
import cv2
import fitz
import openpyxl
import pytesseract
from PIL import Image
print("ocr_name_benchmark dependencies OK")
PY

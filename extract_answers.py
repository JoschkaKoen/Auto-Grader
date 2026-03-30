#!/usr/bin/env python3
"""
extract_answers.py
------------------
Extracts student names + handwritten answers (Q38, Q39, Q40) from scanned IGCSE
answer sheets using Gemini Vision. Processes each page, crops the top half, and
saves results to JSON + CSV.

Requirements:
    pip install google-generativeai pdf2image pillow python-dotenv typing_extensions
    brew install poppler   # macOS

    cd /Users/joschka/Desktop/Programming/Auto-Grader
    source .venv/bin/activate
    python extract_answers.py
    python extract_answers.py output/some_other.pdf
"""

import argparse
import io
import json
import os
import subprocess
import time
from pathlib import Path

import typing_extensions as typing
from dotenv import load_dotenv
from pdf2image import convert_from_path
from PIL import Image
import google.generativeai as genai

# ---------------------------------------------------------------------------
# Load .env
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------

DEFAULT_PDF = "output/20260330135527722.pdf"
OUTPUT_JSON = Path("student_answers_report.json")
OUTPUT_TEX = Path("student_answers_report.tex")
OUTPUT_REPORT = Path("student_answers_report.pdf")
DEBUG_IMAGE_DIR = Path("debug_crops")
SAVE_DEBUG_IMAGES = True

PDF_DPI = 300
JPEG_QUALITY = 95
CROP_TOP_FRACTION = 0.5

GEMINI_MODEL = "gemini-2.0-flash"
API_CALL_DELAY_S = 1.5
MAX_RETRIES = 3
RETRY_BACKOFF_S = 5


# ---------------------------------------------------------------------------
# Structured output schema — enforced at the token level by Gemini
# ---------------------------------------------------------------------------

class StudentAnswers(typing.TypedDict):
    student_name: str
    q38_left: str   # exactly one of: A, B, C, D, or ? if illegible
    q39_left: str
    q40_left: str
    q39_right: str
    q40_right: str
    confidence: str


PROMPT = """\
You are reading a scanned student exam answer sheet for a multiple-choice test.
Each student circles or writes a single letter — A, B, C, or D — for each question.

On the LEFT side of the page (in order from top to bottom):
  - Question 38 answer
  - Question 39 answer
  - Question 40 answer

On the RIGHT side of the page (in order from top to bottom):
  - Question 39 answer
  - Question 40 answer

At the TOP of the page, the student has written their name in English.

Rules:
- For each question field, return ONLY the single letter the student wrote: A, B, C, or D.
- If a letter is illegible or missing, return "?" for that field.
- For student_name, return the exact name as written, or "UNKNOWN" if illegible.
- For confidence, return "high", "medium", or "low" based on overall legibility.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def crop_top(image: Image.Image, fraction: float = CROP_TOP_FRACTION) -> Image.Image:
    """Return the top `fraction` of the image."""
    w, h = image.size
    return image.crop((0, 0, w, int(h * fraction)))


def to_jpeg_bytes(image: Image.Image, quality: int = JPEG_QUALITY) -> bytes:
    """Convert a PIL image to JPEG bytes."""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def call_gemini(model, image_bytes: bytes, page_num: int) -> dict:
    """Call Gemini Vision with structured output + retry + exponential backoff."""
    last_error = None
    backoff = RETRY_BACKOFF_S

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = model.generate_content(
                contents=[
                    {"mime_type": "image/jpeg", "data": image_bytes},
                    PROMPT,
                ],
                generation_config=genai.types.GenerationConfig(
                    temperature=0,
                    max_output_tokens=1024,
                    response_mime_type="application/json",
                    response_schema=StudentAnswers,
                ),
            )
            return json.loads(response.text)

        except Exception as e:
            print(f"    API error (attempt {attempt}/{MAX_RETRIES}): {e}")
            last_error = e

        if attempt < MAX_RETRIES:
            print(f"    Retrying in {backoff}s...")
            time.sleep(backoff)
            backoff *= 2

    return {
        "student_name": "EXTRACTION_ERROR",
        "q38_left": "",
        "q39_left": "",
        "q40_left": "",
        "q39_right": "",
        "q40_right": "",
        "confidence": "failed",
        "error": str(last_error),
    }


def load_existing_results() -> dict[int, dict]:
    """Load existing JSON results so we can resume an interrupted run."""
    if OUTPUT_JSON.exists():
        with open(OUTPUT_JSON, encoding="utf-8") as f:
            records = json.load(f)
        return {r["page_number"]: r for r in records}
    return {}


def save_results(results: list[dict]):
    """Persist current results to JSON."""
    sorted_results = sorted(results, key=lambda r: r["page_number"])
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(sorted_results, f, indent=2, ensure_ascii=False)


def _tex_escape(text: str) -> str:
    """Escape special LaTeX characters."""
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"),
        ("_", r"\_"), ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def generate_report_pdf(results: list[dict]):
    """Generate a LaTeX table and compile to PDF."""
    sorted_results = sorted(results, key=lambda r: r["page_number"])

    rows = []
    for r in sorted_results:
        name = _tex_escape(r.get("student_name", "UNKNOWN"))
        q38l = _tex_escape(r.get("q38_left", "?"))
        q39l = _tex_escape(r.get("q39_left", "?"))
        q40l = _tex_escape(r.get("q40_left", "?"))
        q39r = _tex_escape(r.get("q39_right", "?"))
        q40r = _tex_escape(r.get("q40_right", "?"))
        rows.append(f"        {r['page_number']} & {name} & {q38l} & {q39l} & {q40l} & {q39r} & {q40r} \\\\")

    table_rows = "\n".join(rows)

    tex = f"""\
\\documentclass[a4paper,11pt]{{article}}
\\usepackage[margin=2cm]{{geometry}}
\\usepackage{{booktabs}}
\\usepackage{{longtable}}
\\usepackage{{array}}

\\title{{Student Answers Report}}
\\author{{Auto-Grader}}
\\date{{\\today}}

\\begin{{document}}
\\maketitle

\\begin{{longtable}}{{r l c c c c c}}
    \\toprule
    \\textbf{{Page}} & \\textbf{{Student Name}} & \\textbf{{Q38 (L)}} & \\textbf{{Q39 (L)}} & \\textbf{{Q40 (L)}} & \\textbf{{Q39 (R)}} & \\textbf{{Q40 (R)}} \\\\
    \\midrule
    \\endhead
{table_rows}
    \\bottomrule
\\end{{longtable}}

\\end{{document}}
"""

    with open(OUTPUT_TEX, "w", encoding="utf-8") as f:
        f.write(tex)

    print(f"\nCompiling LaTeX -> {OUTPUT_REPORT} ...")
    result = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", str(OUTPUT_TEX)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  LaTeX compilation failed. Check {OUTPUT_TEX} for errors.")
        print(result.stdout[-500:] if result.stdout else "")
    else:
        print(f"  Report generated: {OUTPUT_REPORT}")

    # Clean up LaTeX auxiliary files
    for ext in (".aux", ".log", ".out"):
        aux = OUTPUT_TEX.with_suffix(ext)
        if aux.exists():
            aux.unlink()


def print_summary(results: list[dict]):
    """Print a quick summary of extraction quality."""
    total = len(results)
    high = sum(1 for r in results if r.get("confidence") == "high")
    medium = sum(1 for r in results if r.get("confidence") == "medium")
    low = sum(1 for r in results if r.get("confidence") == "low")
    failed = sum(1 for r in results if r.get("confidence") == "failed")
    unknown = sum(1 for r in results if r.get("student_name") in ("UNKNOWN", "EXTRACTION_ERROR"))

    print(f"\n{'=' * 50}")
    print(f"  SUMMARY: {total} pages processed")
    print(f"  High confidence:   {high}")
    print(f"  Medium confidence: {medium}")
    print(f"  Low confidence:    {low}")
    print(f"  Failed:            {failed}")
    print(f"  Unreadable names:  {unknown}")
    print(f"{'=' * 50}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract handwritten answers from scanned exam PDFs using Gemini Vision."
    )
    parser.add_argument("pdf", nargs="?", default=DEFAULT_PDF,
                        help=f"Path to input PDF (default: {DEFAULT_PDF})")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"ERROR: PDF not found: {pdf_path}")
        raise SystemExit(1)

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: Set GOOGLE_API_KEY in .env or environment.")
        raise SystemExit(1)

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL)

    if SAVE_DEBUG_IMAGES:
        DEBUG_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    # Resume support
    existing = load_existing_results()
    if existing:
        print(f"Resuming -- {len(existing)} pages already done, skipping them.")

    print(f"Converting PDF to images at {PDF_DPI} DPI (this may take a minute)...")
    pages = convert_from_path(str(pdf_path), dpi=PDF_DPI)
    print(f"{len(pages)} pages found.\n")

    results_map: dict[int, dict] = dict(existing)

    for page_num, page in enumerate(pages, start=1):
        if page_num in results_map:
            print(f"  Page {page_num:3d}/{len(pages)} -- skipped (already processed)")
            continue

        print(f"  Page {page_num:3d}/{len(pages)} -- extracting...", end="", flush=True)

        crop = crop_top(page, CROP_TOP_FRACTION)
        img_bytes = to_jpeg_bytes(crop)

        if SAVE_DEBUG_IMAGES:
            crop.save(DEBUG_IMAGE_DIR / f"page_{page_num:04d}.jpg", quality=85)

        data = call_gemini(model, img_bytes, page_num)
        data["page_number"] = page_num
        results_map[page_num] = data

        conf = data.get("confidence", "?")
        name = data.get("student_name", "?")
        marker = {"high": "OK", "medium": "??", "low": "!!", "failed": "XX"}.get(conf, "??")
        q38l = data.get("q38_left", "?")
        q39l = data.get("q39_left", "?")
        q40l = data.get("q40_left", "?")
        q39r = data.get("q39_right", "?")
        q40r = data.get("q40_right", "?")
        print(f" [{marker}] {name}  |  Q38:{q38l}  Q39L:{q39l}  Q40L:{q40l}  Q39R:{q39r}  Q40R:{q40r}")

        save_results(list(results_map.values()))
        time.sleep(API_CALL_DELAY_S)

    all_results = list(results_map.values())
    print_summary(all_results)
    generate_report_pdf(all_results)
    print(f"\nJSON  -> {OUTPUT_JSON}")
    print(f"LaTeX -> {OUTPUT_TEX}")
    print(f"PDF   -> {OUTPUT_REPORT}")
    if SAVE_DEBUG_IMAGES:
        print(f"Crops -> {DEBUG_IMAGE_DIR}/")


if __name__ == "__main__":
    main()

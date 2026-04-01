"""Evaluate extraction on the first N PDF pages against ground truth."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pdf2image import convert_from_path

from config import API_CALL_DELAY_S, GROUND_TRUTH_PATH, MULTI_PASS_COUNT, PDF_DPI, SAVE_DEBUG_IMAGES

from extraction.ground_truth import (
    calculate_student_accuracy,
    fuzzy_match_name,
    load_ground_truth,
)
from extraction.images import (
    crop_top,
    effective_crop_fraction,
    preprocess_for_extraction,
    to_jpeg_bytes,
)
from extraction.profiles import get_profile
from extraction.providers import create_extraction_client, multi_pass_extract
from extraction.reporting import (
    Colors,
    color_wrong_answer,
    format_accuracy,
)


def extract_first_n_students_eval(
    pdf_path: Path,
    n: int = 12,
    *,
    ground_truth: dict[str, list[str]] | None = None,
    gt_path: Path | None = None,
    client: Any | None = None,
    api_key: str | None = None,
    verbose: bool = True,
    save_results_path: Path | None = None,
    debug_image_dir: Path | None = None,
) -> dict[str, Any]:
    """Extract answers from the first *n* PDF pages, compare to ground truth."""
    load_dotenv()
    profile = get_profile()
    answer_fields = profile.answer_fields

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if n <= 0:
        return {
            "n_requested": n,
            "n_processed": 0,
            "pdf": str(pdf_path.resolve()),
            "students": [],
            "summary": {
                "cumulative_correct": 0,
                "cumulative_total": 0,
                "cumulative_accuracy_pct": 0.0,
            },
        }

    gt = ground_truth if ground_truth is not None else load_ground_truth(gt_path or GROUND_TRUTH_PATH)
    gt_names = list(gt.keys())

    if client is None:
        client = create_extraction_client(api_key)
        if client is None:
            raise RuntimeError(
                "Could not create API client. Set MOONSHOT_API_KEY (Kimi) or "
                "GOOGLE_API_KEY / GEMINI_API_KEY (Gemini), or pass client=."
            )

    if verbose and gt:
        print(f"Ground truth loaded: {len(gt)} students ({', '.join(gt_names)})")

    if verbose:
        print(f"Converting PDF to images at {PDF_DPI} DPI (pages 1–{n} only)...")
    t0 = time.perf_counter()
    pages = convert_from_path(
        str(pdf_path),
        dpi=PDF_DPI,
        thread_count=os.cpu_count() or 4,
        first_page=1,
        last_page=n,
    )
    elapsed = time.perf_counter() - t0
    if verbose:
        print(f"PDF→images ({PDF_DPI} DPI): {elapsed:.2f}s — {len(pages)} page(s).\n")

    if debug_image_dir is None and SAVE_DEBUG_IMAGES:
        debug_image_dir = Path(f"debug/debug_crops_{pdf_path.stem}_first{n}")
    if debug_image_dir and SAVE_DEBUG_IMAGES:
        debug_image_dir.mkdir(parents=True, exist_ok=True)

    cumulative_correct = 0
    cumulative_total = 0
    student_rows: list[dict[str, Any]] = []

    for page_num, page in enumerate(pages, start=1):
        if verbose:
            print(f"  Page {page_num:3d}/{len(pages)} -- extracting...", end="", flush=True)

        crop = crop_top(page, effective_crop_fraction())
        processed = preprocess_for_extraction(crop)
        img_bytes = to_jpeg_bytes(processed)
        if debug_image_dir and SAVE_DEBUG_IMAGES:
            processed.save(debug_image_dir / f"page_{page_num:04d}.jpg", quality=85)

        data = multi_pass_extract(client, img_bytes, page_num, profile, passes=MULTI_PASS_COUNT)
        data["page_number"] = page_num

        name = data.get("student_name", "?")
        conf = data.get("confidence", "?")
        marker = {"high": "OK", "medium": "??", "low": "!!", "failed": "XX"}.get(conf, "??")
        nc = (
            (data.get("student_name_confidence") or "?")[0].upper()
            if data.get("student_name_confidence")
            else "?"
        )
        c38lt = (data.get("q38_left_top_confidence") or "?")[0].upper() if data.get("q38_left_top_confidence") else "?"
        c39l = (data.get("q39_left_confidence") or "?")[0].upper() if data.get("q39_left_confidence") else "?"
        c40l = (data.get("q40_left_confidence") or "?")[0].upper() if data.get("q40_left_confidence") else "?"
        c38lb = (data.get("q38_left_bottom_confidence") or "?")[0].upper() if data.get("q38_left_bottom_confidence") else "?"
        c39r = (data.get("q39_right_confidence") or "?")[0].upper() if data.get("q39_right_confidence") else "?"
        c40r = (data.get("q40_right_confidence") or "?")[0].upper() if data.get("q40_right_confidence") else "?"

        q38lt_raw = data.get("q38_left_top", "?")
        q39l_raw = data.get("q39_left", "?")
        q40l_raw = data.get("q40_left", "?")
        q38lb_raw = data.get("q38_left_bottom", "?")
        q39r_raw = data.get("q39_right", "?")
        q40r_raw = data.get("q40_right", "?")

        matched: str | None = None
        gt_answers: list[str] | None = None
        per_field: list[dict[str, Any]] = []
        acc_here = 0.0
        student_acc_str = "N/A"
        cumulative_acc_str = "N/A"

        q38lt, q39l, q40l, q38lb, q39r, q40r = q38lt_raw, q39l_raw, q40l_raw, q38lb_raw, q39r_raw, q40r_raw

        if gt and name not in ("UNKNOWN", "EXTRACTION_ERROR", "?"):
            matched = fuzzy_match_name(name, gt_names)
            if matched:
                gt_answers = gt[matched]
                gt_pad = list(gt_answers) + [""] * len(answer_fields)
                gt_pad = gt_pad[: len(answer_fields)]
                for i, field in enumerate(answer_fields):
                    ex = data.get(field, "?")
                    gv = gt_pad[i]
                    eu = str(ex).upper().strip()
                    gu = gv.upper().strip()
                    ok = eu == gu and eu not in ("", "?")
                    per_field.append(
                        {"field": field, "extracted": ex, "ground_truth": gv, "correct": ok}
                    )
                    cumulative_total += 1
                    if ok:
                        cumulative_correct += 1

                q38lt = color_wrong_answer(q38lt_raw, gt_pad[0])
                q39l = color_wrong_answer(q39l_raw, gt_pad[1])
                q40l = color_wrong_answer(q40l_raw, gt_pad[2])
                q38lb = color_wrong_answer(q38lb_raw, gt_pad[3])
                q39r = color_wrong_answer(q39r_raw, gt_pad[4])
                q40r = color_wrong_answer(q40r_raw, gt_pad[5])

                acc_here = calculate_student_accuracy(data, gt_pad, answer_fields)
                student_acc_str = format_accuracy(acc_here)
                cum_pct = (cumulative_correct / cumulative_total * 100) if cumulative_total else 0.0
                cumulative_acc_str = format_accuracy(cum_pct)
                data["student_accuracy"] = acc_here
                data["matched_ground_truth_name"] = matched

        student_rows.append(
            {
                "page_number": page_num,
                "extracted": data,
                "matched_ground_truth_name": matched,
                "ground_truth_answers": gt_answers,
                "per_field": per_field,
                "accuracy_here_pct": acc_here,
            }
        )

        if verbose:
            print(
                f" [{marker}] {name}({nc})  |  Q38L↑:{q38lt}({c38lt})  Q39L:{q39l}({c39l})  "
                f"Q40L:{q40l}({c40l})  Q38L↓:{q38lb}({c38lb})  Q39R:{q39r}({c39r})  Q40R:{q40r}({c40r})  "
                f"|  Acc here: {student_acc_str} / Cum: {cumulative_acc_str}{Colors.RESET}"
            )

        time.sleep(API_CALL_DELAY_S)

    cum_pct = (cumulative_correct / cumulative_total * 100) if cumulative_total else 0.0
    out: dict[str, Any] = {
        "n_requested": n,
        "n_processed": len(pages),
        "pdf": str(pdf_path.resolve()),
        "students": student_rows,
        "summary": {
            "cumulative_correct": cumulative_correct,
            "cumulative_total": cumulative_total,
            "cumulative_accuracy_pct": round(cum_pct, 2),
        },
    }

    if save_results_path:
        serializable = {
            "n_requested": out["n_requested"],
            "n_processed": out["n_processed"],
            "pdf": out["pdf"],
            "summary": out["summary"],
            "students": [
                {
                    "page_number": s["page_number"],
                    "extracted": {k: v for k, v in s["extracted"].items() if k != "error"},
                    "matched_ground_truth_name": s["matched_ground_truth_name"],
                    "ground_truth_answers": s["ground_truth_answers"],
                    "per_field": s["per_field"],
                    "accuracy_here_pct": s["accuracy_here_pct"],
                }
                for s in student_rows
            ],
        }
        save_results_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_results_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)
        if verbose:
            print(f"\nEval JSON saved -> {save_results_path}")

    return out

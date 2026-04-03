"""Terminal colors, JSON I/O, LaTeX/PDF report, extraction summary."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from pipeline.extraction.ground_truth import fuzzy_match_name


class Colors:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"


def format_accuracy(acc: float) -> str:
    """Format accuracy as percentage string."""
    return f"{acc:.0f}%"


def color_wrong_answer(value: str, gt_value: str) -> str:
    """Return the value in red if it doesn't match ground truth, green if correct."""
    val_upper = value.upper().strip() if value else ""
    gt_upper = gt_value.upper().strip() if gt_value else ""

    if not val_upper or val_upper == "?":
        return f"{Colors.RED}{value}{Colors.RESET}"
    if val_upper == gt_upper:
        return f"{Colors.GREEN}{value}{Colors.RESET}"
    return f"{Colors.RED}{value}{Colors.RESET}"


def load_existing_results(output_json: Path) -> dict[int, dict]:
    """Load existing JSON results so we can resume an interrupted run."""
    if not output_json.exists():
        return {}
    try:
        with open(output_json, encoding="utf-8") as f:
            records = json.load(f)
        return {r["page_number"]: r for r in records if "page_number" in r}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        print(f"WARNING: Could not parse existing results from {output_json} ({e}), starting fresh.")
        return {}


def save_results(results: list[dict], output_json: Path) -> None:
    """Persist current results to JSON."""
    sorted_results = sorted(results, key=lambda r: r.get("page_number", 0))
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(sorted_results, f, indent=2, ensure_ascii=False)


def _tex_escape(text: str) -> str:
    """Escape special LaTeX characters."""
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def generate_report_pdf(results: list[dict], output_tex: Path, output_report: Path) -> None:
    """Generate a LaTeX table and compile to PDF."""
    sorted_results = sorted(results, key=lambda r: r.get("page_number", 0))

    rows = []
    for r in sorted_results:
        page_num = r.get("page_number", "?")
        name = _tex_escape(r.get("student_name", "UNKNOWN"))
        q38lt = _tex_escape(r.get("q38_left_top", "?"))
        q39l = _tex_escape(r.get("q39_left", "?"))
        q40l = _tex_escape(r.get("q40_left", "?"))
        q38lb = _tex_escape(r.get("q38_left_bottom", "?"))
        q39r = _tex_escape(r.get("q39_right", "?"))
        q40r = _tex_escape(r.get("q40_right", "?"))
        rows.append(
            f"        {page_num} & {name} & {q38lt} & {q39l} & {q40l} & {q38lb} & {q39r} & {q40r} \\\\"
        )

    table_rows = "\n".join(rows)

    tex = f"""\
\\documentclass[a4paper,11pt]{{article}}
\\usepackage[margin=2cm]{{geometry}}
\\usepackage{{booktabs}}
\\usepackage{{longtable}}
\\usepackage{{array}}
\\usepackage{{fontspec}}
\\usepackage{{xeCJK}}
\\setCJKmainfont{{PingFang SC Regular}}[BoldFont=PingFang SC Semibold]

\\title{{Student Answers Report}}
\\author{{Auto-Grader}}
\\date{{\\today}}

\\begin{{document}}
\\maketitle

\\begin{{longtable}}{{r l c c c c c c}}
    \\toprule
    \\textbf{{Page}} & \\textbf{{Student Name}} & \\textbf{{Q38 L↑}} & \\textbf{{Q39 L}} & \\textbf{{Q40 L}} & \\textbf{{Q38 L↓}} & \\textbf{{Q39 R}} & \\textbf{{Q40 R}} \\\\
    \\midrule
    \\endhead
{table_rows}
    \\bottomrule
\\end{{longtable}}

\\end{{document}}
"""

    with open(output_tex, "w", encoding="utf-8") as f:
        f.write(tex)

    print(f"\nCompiling LaTeX -> {output_report} ...")
    result = subprocess.run(
        ["xelatex", "-interaction=nonstopmode", str(output_tex)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  LaTeX compilation failed. Check {output_tex} for errors.")
        print(result.stdout[-500:] if result.stdout else "")
    else:
        print(f"  Report generated: {output_report}")

    for ext in (".aux", ".log", ".out"):
        aux = output_tex.with_suffix(ext)
        if aux.exists():
            aux.unlink()


def print_summary(
    results: list[dict],
    ground_truth: dict[str, list[str]] | None = None,
    *,
    answer_fields: list[str],
) -> None:
    """Print a quick summary of extraction quality and accuracy."""
    total = len(results)
    high = sum(1 for r in results if r.get("confidence") == "high")
    medium = sum(1 for r in results if r.get("confidence") == "medium")
    low = sum(1 for r in results if r.get("confidence") == "low")
    failed = sum(1 for r in results if r.get("confidence") == "failed")
    unknown = sum(1 for r in results if r.get("student_name") in ("UNKNOWN", "EXTRACTION_ERROR"))

    overall_acc = 0.0
    total_correct = 0
    total_answer_fields = 0
    matched_students = 0

    if ground_truth:
        gt_names = list(ground_truth.keys())

        for r in results:
            name = r.get("student_name", "")
            if name not in ("UNKNOWN", "EXTRACTION_ERROR", ""):
                matched_gt_name = fuzzy_match_name(name, gt_names)
                if matched_gt_name:
                    matched_students += 1
                    gt_answers = ground_truth[matched_gt_name]
                    for i, field in enumerate(answer_fields):
                        extracted_val = r.get(field, "?").upper().strip()
                        gt_val = gt_answers[i].upper().strip() if i < len(gt_answers) else ""
                        total_answer_fields += 1
                        if extracted_val == gt_val and extracted_val not in ("", "?"):
                            total_correct += 1

        overall_acc = (total_correct / total_answer_fields * 100) if total_answer_fields > 0 else 0

    print(f"\n{'=' * 60}")
    print(f"  EXTRACTION SUMMARY: {total} pages processed")
    print(f"  High confidence:   {high}")
    print(f"  Medium confidence: {medium}")
    print(f"  Low confidence:    {low}")
    print(f"  Failed:            {failed}")
    print(f"  Unreadable names:  {unknown}")

    if ground_truth:
        print(f"\n  ACCURACY SUMMARY:")
        print(f"  Students matched to ground truth: {matched_students}/{len(ground_truth)}")
        print(f"  Overall accuracy: {overall_acc:.1f}% ({total_correct}/{total_answer_fields} correct)")

    print(f"{'=' * 60}")

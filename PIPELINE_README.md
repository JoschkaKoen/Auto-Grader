# Package layout (grading)

The grading flow is split into **domain packages** at the repo root. [`grade.py`](grade.py) wires them in order (mostly via late imports in `_run`).

## Subpackages

| Folder | Role |
|--------|------|
| [`extraction/`](extraction/) | AI vision extraction: profiles, providers (Gemini/Kimi), reporting helpers. |
| [`preprocessing/`](preprocessing/) | Raw class scan → `cleaned_scan.pdf` (blank removal, autorotate, deskew, optional debug PDFs). |
| [`scaffold/`](scaffold/) | Vector exam + answer key → `ExamScaffold`, cache, figure PNGs, boxes on empty exam, geometry onto scans. |
| [`marking/`](marking/) | Kimi-driven steps: parse instruction, find folder, assign pages, detect attempted questions, grade. |
| [`reports/`](reports/) | Terminal tables / summaries and LaTeX → PDF report. |
| [`shared/`](shared/) | Dataclasses, path helpers, CLI formatting, roster and ground-truth I/O. |

## Terminal output

[`shared/terminal_ui.py`](shared/terminal_ui.py) formats `grade.py` progress. By default, step headers are **compact** (single line). Set **`PIPELINE_VERBOSE=1`** or **`GRADE_VERBOSE=1`** to restore wide step banners (`═` rules) and extra detail from some modules (e.g. Kimi connection line, extraction debug).

## `grade.py` step → module map

| Step | Module (import path) | Notes |
|------|----------------------|--------|
| 1 | `marking.parse_instruction` | `parse_prompt(...)` |
| 2 | `marking.find_exam_folder` | `find_folder(...)` |
| 3 | `shared.load_student_list` | `read_student_list(...)` |
| 4 | `scaffold.generate_scaffold` | `build_scaffold(...)` |
| 5 | `preprocessing.start_scan` | `cleanup_pdf(...)` |
| 6 | `marking.assign_pages_to_students` | `assign_pages(...)` |
| 7 | `marking.detect_answered_questions` | `detect_answered_exercises(...)` |
| 8 | `marking.grade_answers` | `grade_students(...)` |
| 9 | `reports.print_results` | `print_*` helpers |
| 10 | `shared.load_ground_truth` | optional evaluation |
| 11 | `reports.generate_report` | `generate_report(...)` |

## Vector PDF parsing

[`scaffold/pdf_parser/`](scaffold/pdf_parser/) implements layout detection, regions, content extraction, and assembly into `Question` trees. Import the stable surface from `scaffold.pdf_parser` (same symbols as before earlier refactors).

"""Paths for per-exam derived artifacts (under ``output/<stem>/`` by default)."""

from __future__ import annotations

from pathlib import Path


def exam_artifact_dir(exam_folder: Path, output_base: str | Path = "output") -> Path:
    """Directory for cleaned scans, scaffold cache, images, and debug PDFs.

    *exam_folder* is the exam input directory (raw PDFs, roster). *stem* is the
    folder name with spaces replaced by underscores.
    """
    stem = exam_folder.name.replace(" ", "_")
    return Path(output_base) / stem


def artifact_scaffold_cache_path(artifact_dir: Path) -> Path:
    return artifact_dir / "scaffolds" / "scaffold_cache.json"


def find_scaffold_cache_file(
    exam_folder: Path, output_base: str | Path = "output"
) -> Path | None:
    """First existing scaffold cache: artifact dir, then legacy locations under *exam_folder*."""
    ad = exam_artifact_dir(exam_folder, output_base)
    for p in (
        artifact_scaffold_cache_path(ad),
        exam_folder / "scaffolds" / "scaffold_cache.json",
        exam_folder / "scaffold_cache.json",
    ):
        if p.is_file():
            return p
    return None

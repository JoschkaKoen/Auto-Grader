"""Exam profiles: prompt + schema + answer field order."""

from __future__ import annotations

from config import EXAM_PROFILE

from extraction.profiles.base import ExamProfile


def get_profile() -> ExamProfile:
    if EXAM_PROFILE == "igcse_physics":
        from extraction.profiles.igcse_physics import PROFILE

        return PROFILE
    raise ValueError(f"Unknown exam profile: {EXAM_PROFILE!r}. Set EXAM_PROFILE in config.py.")

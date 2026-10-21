"""Study & coach — the teaching queue, the decks, the shepherd's path (V3 migration step 6, last).

The witness app shows the way of study: the Words in Red, the library decks, and the coach's
overview and one next step. It composes the core's read doors and keeps no learner state of its own.

READ (here, safe):
- `teachings()`          → the Words in Red by group            (GET /teachings)
- `decks()`              → the library decks                    (GET /decks)
- `coach_overview(subj)` → a subject's tracks and units         (GET /coach/overview)
- `coach_next(subj)`     → the one next unit                    (GET /coach/next)
- `playbook()`           → the playbook entries                 (GET /playbook)

WRITES (a declared seam — NOT performed here): recording mastery (`/coach/mastery`), creating or
exporting/importing a study (`/study`, `/study/export`, `/study/import`), saving a trajectory
(`/trajectory` POST), and submitting a playbook entry (`/playbook/submit`) are the learner's own
acts, kept as their record. The app composes them only as the learner's authorized request; those
doors stay out of CORE_DOORS. See docs/STUDY.md.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .core_client import CoreClient

STUDY_WRITE_DOORS = ("/coach/mastery", "/study", "/study/export", "/study/import",
                     "/trajectory", "/playbook/submit")


def teachings(*, client: Optional[CoreClient] = None) -> Dict[str, Any]:
    return (client or CoreClient()).teachings()


def decks(*, client: Optional[CoreClient] = None) -> Dict[str, Any]:
    return (client or CoreClient()).decks()


def coach_overview(subject: str = "", *, client: Optional[CoreClient] = None) -> Dict[str, Any]:
    return (client or CoreClient()).coach_overview(subject)


def coach_next(subject: str = "", *, client: Optional[CoreClient] = None) -> Dict[str, Any]:
    return (client or CoreClient()).coach_next(subject)


def playbook(*, client: Optional[CoreClient] = None) -> Dict[str, Any]:
    return (client or CoreClient()).playbook()

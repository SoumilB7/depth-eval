"""Scorecards — the ARC-AGI open/update/close lifecycle, local and minimal.

A card is opened before any agent runs, every finished run reports into it,
and closing it writes one JSON report under the recordings directory:

    {recordings_dir}/{card_id}.scorecard.json

Closing is SIGINT-safe by design: whatever ran before Ctrl+C still lands in
the report (main.py wires that). EVERY launched run is a row — its
outcome (graded / error / unfinished, see agent.py) and, when graded, the
stage verdict (first divergence stage + kind, stages matched of expected).
Only graded runs are scored: `solved` counts over `graded`, and runs that
failed on our side are listed, never silently dropped. This file only
carries results, it never computes truth.
"""

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from .recorder import get_recordings_dir


@dataclass(frozen=True)
class RunScore:
    """One finished run, as reported by an agent."""

    spec: str
    agent: str
    outcome: str                  # graded | error | unfinished
    exact: bool | None            # None unless graded, as below
    first_divergence: int | None
    divergence_kind: str | None
    stages_matched: int | None
    stages_expected: int | None
    seconds: float
    error: str | None = None


@dataclass
class Scorecard:
    card_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tags: list[str] = field(default_factory=list)
    opened: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    scores: list[RunScore] = field(default_factory=list)

    def add(self, score: RunScore) -> None:
        self.scores.append(score)

    def report(self) -> dict:
        return {
            "card_id": self.card_id,
            "tags": self.tags,
            "opened": self.opened,
            "closed": datetime.now(timezone.utc).isoformat(),
            "runs": len(self.scores),
            "graded": sum(1 for s in self.scores if s.outcome == "graded"),
            "solved": sum(1 for s in self.scores if s.exact),
            "errors": [s.spec for s in self.scores if s.outcome == "error"],
            "unfinished": [s.spec for s in self.scores if s.outcome == "unfinished"],
            "scores": [asdict(s) for s in self.scores],
        }

    def close(self) -> dict:
        """Finalize, write the report to disk, and return it."""
        report = self.report()
        recordings_dir = get_recordings_dir()
        os.makedirs(recordings_dir, exist_ok=True)
        path = os.path.join(recordings_dir, f"{self.card_id}.scorecard.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        report["path"] = path
        return report

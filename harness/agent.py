"""The agent contract — the ARC-AGI harness loop, collapsed to one answer.

Their ground rules, kept:

- the base class owns the run: timing, recording, the outcome, cleanup —
  an agent can never forget to record or leave a run unaccounted for;
- a concrete agent overrides ONE hook: solve(observation);
- every run is recorded; a recording filename is itself a valid agent
  (Playback) that replays the answer without touching any model — so
  grading can change and every past reply is re-graded for free.

Single-shot and blind (Soumil, 2026-09-26): an agent sees the observation
and nothing else, answers once, and never learns how it was graded — no
path from our answers back toward a solver. Whatever tool loop an agent
runs to produce its answer (harness/calculator.py) stays inside solve().

Every run ends in exactly one outcome:
    graded      solve() returned an answer; the environment graded it
    error       solve() raised — our side failed (a crash, an API error, a
                missing reply file); not scored, listed for a re-run
    unfinished  the sweep stopped before solve() returned (Ctrl+C)
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from .env import QuestionEnvironment, SubmissionResult
from .recorder import Recorder

logger = logging.getLogger()


class Agent(ABC):
    """Interface for an agent that answers one question environment."""

    def __init__(
        self,
        card_id: str,
        env: QuestionEnvironment,
        agent_name: str,
        record: bool = True,
        tags: Optional[list[str]] = None,
    ) -> None:
        self.card_id = card_id
        self.env = env
        self.agent_name = agent_name
        self.tags = tags or []
        self.result: Optional[SubmissionResult] = None
        self.error: Optional[str] = None
        self.timer: float = 0.0
        self.finished_at: float = 0.0
        if record:
            self.recorder = Recorder(prefix=self.name)
            logger.info(f"recording {self.name} into {self.recorder.filename}")

    @property
    def name(self) -> str:
        return f"{self.env.spec}.{self.__class__.__name__.lower()}"

    @property
    def is_playback(self) -> bool:
        return type(self) is Playback

    @property
    def outcome(self) -> str:
        if self.result is not None:
            return "graded"
        return "error" if self.error is not None else "unfinished"

    @property
    def seconds(self) -> float:
        if not self.timer:
            return 0.0
        return round((self.finished_at or time.time()) - self.timer, 2)

    def record(self, data: dict[str, Any]) -> None:
        """Append one event to this run's recording (never during playback)."""
        if hasattr(self, "recorder") and not self.is_playback:
            self.recorder.record(data)

    def main(self) -> None:
        """The run: one answer, graded — or the reason there is none."""
        self.timer = time.time()
        self.record({"observation": self.env.observation})
        try:
            answer = self.solve(self.env.observation)
        except Exception as e:  # our side failed: recorded, never scored
            self.error = f"{type(e).__name__}: {e}"
            self.record({"error": self.error})
            logger.error(f"{self.env.spec} - error: {self.error}")
        else:
            self.result = self.env.submit(answer)
            self.record({
                "answer": answer,
                "exact": self.result.exact,
                "first_divergence": self.result.first_divergence,
                "divergence_kind": self.result.divergence_kind,
                "stages_matched": self.result.stages_matched,
                "detail": self.result.detail,
                "stage_report": self.result.stage_report,
            })
            logger.info(
                f"{self.env.spec} - exact={self.result.exact} "
                f"first_divergence={self.result.first_divergence} "
                f"({self.result.divergence_kind}) "
                f"stages {self.result.stages_matched}/{self.result.stages_expected}"
            )
        self.finished_at = time.time()
        logger.info(f"finished {self.name}: {self.outcome} in {self.seconds}s")

    @abstractmethod
    def solve(self, observation: dict) -> object:
        """Produce the answer: the JSON stage log the prompt asks for, as an
        object or as the raw reply text (the environment parses either).
        Raise when our side cannot produce one — that run becomes `error`."""
        raise NotImplementedError


class Playback(Agent):
    """Replays the answer from a recording — re-grading without a model.

    agent_name is the recording filename; the recorded answer is submitted
    against a freshly generated (deterministic) environment.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.recorder = Recorder(
            prefix=Recorder.get_prefix(self.agent_name), filename=self.agent_name
        )
        self.recorded_answers: list[object] = [
            event["data"]["answer"]
            for event in self.recorder.get()
            if "answer" in event.get("data", {})
        ]

    def solve(self, observation: dict) -> object:
        if not self.recorded_answers:
            raise ValueError(f"{self.agent_name} holds no answer")
        return self.recorded_answers[-1]  # the answer the run stood on

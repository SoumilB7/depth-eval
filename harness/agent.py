"""The agent contract — the ARC-AGI harness loop, collapsed to single-shot.

Their ground rules, kept exactly:

- the base class owns the loop: attempt guard, counters, timing, recording,
  cleanup — an agent can never loop forever or forget to record;
- a concrete agent overrides exactly TWO hooks: solve() and is_done();
- every attempt is recorded; a recording filename is itself a valid agent
  (Playback) that replays answers without touching any model.

What collapsed: their choose_action/step cycle is our solve/submit — the
evaluated model answers a question once (or a few retries), it never plays
turns. Tools, prompts, and providers are later layers on top of solve().
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

    MAX_ATTEMPTS: int = 3  # guard so a retrying agent can't loop forever

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
        self.attempts: list[SubmissionResult] = []
        self.timer: float = 0.0
        self._cleanup = True
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
    def result(self) -> Optional[SubmissionResult]:
        """The graded answer this run stands on: the last attempt."""
        return self.attempts[-1] if self.attempts else None

    @property
    def seconds(self) -> float:
        return round(time.time() - self.timer, 2)

    def main(self) -> None:
        """The loop. Solve until done or out of attempts, then clean up."""
        self.timer = time.time()
        if hasattr(self, "recorder") and not self.is_playback:
            self.recorder.record({"observation": self.env.observation})
        while not self.is_done(self.attempts) and len(self.attempts) < self.MAX_ATTEMPTS:
            answer = self.solve(self.env.observation, self.attempts)
            result = self.env.submit(answer)
            self.append_attempt(result)
            logger.info(
                f"{self.env.spec} - attempt {len(self.attempts)}: "
                f"exact={result.exact} first_wrong={result.first_wrong}"
            )
        self.cleanup()

    def append_attempt(self, result: SubmissionResult) -> None:
        self.attempts.append(result)
        if hasattr(self, "recorder") and not self.is_playback:
            self.recorder.record(
                {
                    "attempt": len(self.attempts),
                    "answer": result.answer,
                    "exact": result.exact,
                    "first_wrong": result.first_wrong,
                }
            )

    def cleanup(self) -> None:
        """Called once after the loop ends."""
        if self._cleanup:
            self._cleanup = False
            logger.info(
                f"finished {self.name}: {len(self.attempts)} attempt(s) "
                f"in {self.seconds}s"
            )

    @abstractmethod
    def is_done(self, attempts: list[SubmissionResult]) -> bool:
        """Decide whether to stop before MAX_ATTEMPTS is hit."""
        raise NotImplementedError

    @abstractmethod
    def solve(self, observation: dict, attempts: list[SubmissionResult]) -> list[int]:
        """Produce the final list for this observation. Prior graded
        attempts are visible so retrying agents can adapt."""
        raise NotImplementedError


class Playback(Agent):
    """Replays answers from a recording — re-grading without a model.

    agent_name is the recording filename; recorded answers are re-submitted
    in order against a freshly generated (deterministic) environment.
    """

    MAX_ATTEMPTS = 1_000_000  # a recording defines its own length

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.recorder = Recorder(
            prefix=Recorder.get_prefix(self.agent_name), filename=self.agent_name
        )
        self.recorded_answers: list[list[int]] = [
            event["data"]["answer"]
            for event in self.recorder.get()
            if "answer" in event.get("data", {})
        ]
        logger.info(
            f"loaded {len(self.recorded_answers)} answers from {self.agent_name}"
        )

    def is_done(self, attempts: list[SubmissionResult]) -> bool:
        return len(attempts) >= len(self.recorded_answers)

    def solve(self, observation: dict, attempts: list[SubmissionResult]) -> list[int]:
        return self.recorded_answers[len(attempts)]

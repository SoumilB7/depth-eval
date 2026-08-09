"""The zero-dependency baseline: answers with random integers.

Exists for the same reason theirs does — it exercises the ENTIRE pipeline
(env -> agent -> recording -> scorecard) with no API key, no network, no
model. If `--agent=random` runs clean, the harness itself is sound.
"""

import random

from ..agent import Agent
from ..env import SubmissionResult


class Random(Agent):
    """Answers once, with uniform random values shaped like the start list."""

    def is_done(self, attempts: list[SubmissionResult]) -> bool:
        return len(attempts) >= 1

    def solve(self, observation: dict, attempts: list[SubmissionResult]) -> list[int]:
        rng = random.Random()
        return [rng.randint(0, 100) for _ in observation["start"]]

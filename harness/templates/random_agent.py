"""The zero-dependency baseline: a random stage log.

Exists for the same reason theirs does — it exercises the ENTIRE pipeline
(env -> agent -> recording -> scorecard) with no API key, no network, no
model. If `--agent=random` runs clean, the harness itself is sound. It
answers in the contract's shape (one stage per instruction, listed order)
so the grader sees a well-formed log that is wrong on the numbers.
"""

import random

from ..agent import Agent


class Random(Agent):
    """Answers with uniform random lists shaped like the start list."""

    def solve(self, observation: dict) -> dict:
        rng = random.Random()
        length = len(observation["start"])
        stages = [
            {"ran": number, "state": [rng.randint(0, 100) for _ in range(length)]}
            for number in range(1, observation["steps"] + 1)
        ]
        return {"stages": stages, "final": stages[-1]["state"]}

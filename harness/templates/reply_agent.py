"""A reply written by an outside solver — the bridge for any model driven
outside this process: a hand-run in a chat window, a reasoning-only
subagent, another orchestrator. It submits the reply text found at

    {ANSWERS_DIR}/{spec}.txt        (ANSWERS_DIR env var, default "answers")

exactly as written; the environment parses and grades it (harness/answer.py).
A missing file means no solver answered — our side's gap, not the model's
answer — so the run ends as `error` (unscored, listed for a re-run). An
empty or garbled file IS an answer and grades as malformed. Outside
solvers get no calculators: reply runs are text-only runs.
"""

import os

from ..agent import Agent


def get_answers_dir() -> str:
    """Where reply files live (env var wins, like every knob here)."""
    return os.environ.get("ANSWERS_DIR", "answers")


class Reply(Agent):
    """Submits the pre-written reply for its spec."""

    def solve(self, observation: dict) -> str:
        path = os.path.join(get_answers_dir(), f"{observation['spec']}.txt")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"no reply file {path}")
        with open(path, encoding="utf-8") as f:
            return f.read()

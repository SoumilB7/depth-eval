"""The grading harness. Engine (depth_eval) stays pure; this package runs it.

AVAILABLE_AGENTS is an EXPLICIT registry (coding norm #2 — no
__subclasses__ auto-discovery): an agent exists in the harness if and only
if it is listed here. Recording filenames are additionally accepted as
agent names by the Swarm and replay through Playback.
"""

from .agent import Agent, Playback
from .env import QuestionEnvironment, RunSpec, SubmissionResult, make
from .recorder import Recorder
from .scorecard import RunScore, Scorecard
from .swarm import Swarm
from .templates import Random

AVAILABLE_AGENTS: dict[str, type[Agent]] = {
    "random": Random,
}

__all__ = [
    "Agent",
    "Playback",
    "AVAILABLE_AGENTS",
    "QuestionEnvironment",
    "RunSpec",
    "SubmissionResult",
    "make",
    "Recorder",
    "RunScore",
    "Scorecard",
    "Swarm",
    "Random",
]

"""The sandbox side: a question as a playable environment.

Smallest possible mirror of the ARC-AGI toolkit split (Arcade factory ->
EnvironmentWrapper): a factory turns a run spec into an environment; the
environment exposes an observation and grades submissions. This is the ONLY
place the harness touches the engine — depth_eval stays a pure library.

A run spec is the exact string testruns/ already uses for filenames:

    {config}-s{steps}-L{length}-ls{list_seed}-is{instruction_seed}
    e.g. default-s10-L10-ls42-is37

The observation is raw parts for now (instruction text, start list,
companion rows). Prompt assembly — the conventions preamble, which rows to
surface — is a later, deliberate layer; agents decide nothing about truth,
they only see the observation and hand back a list of integers.
"""

import re
from dataclasses import dataclass

from depth_eval import GeneratorConfig, Question, generate, load_config

SPEC_PATTERN = re.compile(
    r"^(?P<config>[a-z0-9_]+)"
    r"-s(?P<steps>\d+)-L(?P<length>\d+)"
    r"-ls(?P<list_seed>\d+)-is(?P<instruction_seed>\d+)$"
)


@dataclass(frozen=True)
class RunSpec:
    """One run identity, round-trippable to/from its filename form."""

    config: str
    steps: int
    length: int
    list_seed: int
    instruction_seed: int

    @classmethod
    def parse(cls, spec: str) -> "RunSpec":
        match = SPEC_PATTERN.match(spec)
        if match is None:
            raise ValueError(
                f"bad run spec {spec!r} — expected "
                "{config}-s{steps}-L{length}-ls{list_seed}-is{instruction_seed}"
            )
        return cls(
            config=match["config"],
            steps=int(match["steps"]),
            length=int(match["length"]),
            list_seed=int(match["list_seed"]),
            instruction_seed=int(match["instruction_seed"]),
        )

    def __str__(self) -> str:
        return (
            f"{self.config}-s{self.steps}-L{self.length}"
            f"-ls{self.list_seed}-is{self.instruction_seed}"
        )


@dataclass(frozen=True)
class SubmissionResult:
    """One graded answer. `first_wrong` is the first diverging position
    (a length mismatch diverges at the shorter list's end), None when exact."""

    answer: list[int]
    expected: list[int]
    exact: bool
    first_wrong: int | None


class QuestionEnvironment:
    """One question, playable: observation out, graded submissions in."""

    def __init__(self, spec: RunSpec, config: GeneratorConfig) -> None:
        self.spec = spec
        self.question: Question = generate(
            list_seed=spec.list_seed,
            instruction_seed=spec.instruction_seed,
            steps=spec.steps,
            length=spec.length,
            config=config,
        )

    @property
    def observation(self) -> dict:
        """Everything an agent may see. Never includes the answer or trace."""
        return {
            "spec": str(self.spec),
            "text": self.question.text,
            "start": list(self.question.start),
            "companions": [list(row) for row in self.question.companions],
        }

    def submit(self, answer: list[int]) -> SubmissionResult:
        expected = list(self.question.final)
        answer = list(answer)
        exact = answer == expected
        first_wrong = None
        if not exact:
            first_wrong = next(
                (i for i, (a, e) in enumerate(zip(answer, expected)) if a != e),
                min(len(answer), len(expected)),
            )
        return SubmissionResult(answer, expected, exact, first_wrong)


def make(spec: str) -> QuestionEnvironment:
    """Factory: run spec string -> ready environment (the Arcade analog)."""
    parsed = RunSpec.parse(spec)
    return QuestionEnvironment(parsed, load_config(parsed.config))

"""The sandbox side: a question as a playable environment.

Smallest possible mirror of the ARC-AGI toolkit split (Arcade factory ->
EnvironmentWrapper): a factory turns a run spec into an environment; the
environment exposes an observation and grades submissions. This is the ONLY
place the harness touches the engine — depth_eval stays a pure library.

A run spec is the exact string testruns/ already uses for filenames:

    {config}-s{steps}-L{length}-ls{list_seed}-is{instruction_seed}
    e.g. default-s10-L10-ls42-is37

The observation carries the complete prompt a model is sent —
`render_prompt`, verbatim, because the wording is part of the question's
meaning and lives in the engine — plus the raw parts for agents that need
them. The answer is the JSON stage log the prompt asks for, and grading is
STAGE BY STAGE (decision 13, ruling 1: a line whose work is later
overwritten still counts). The primary score is the first divergence
stage — the same comparison testruns/examples/compare.py applied to every
trial so far — with the kind of divergence named.
"""

import re
from dataclasses import dataclass

from depth_eval import GeneratorConfig, Question, Step, generate, load_config, render_prompt

from .answer import MalformedAnswer, parse_stage_log

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
    """One graded stage log.

    first_divergence: 1-based index of the first stage the model got wrong,
    None when exact. divergence_kind names it:
      order     — it ran the wrong instruction at that stage
      state     — right instruction, wrong list
      count     — every stage matched but the log stopped early or ran on
                  (index = the first missing or surplus stage)
      final     — every stage matched, the final list does not
                  (index = stages_expected + 1)
      malformed — not a stage log at all (index 0: before any stage)
    stages_matched: stages correct before that point — the depth reached.
    stage_report: every true stage side by side with the model's — truth_ran,
      truth, model_ran, model (None where the log has no such stage), ok,
      wrong_positions — so a miss can be read stage by stage (and a later
      "healed" error is visible); empty for a malformed answer.
    """

    answer: object
    expected: list[dict]
    stages_expected: int
    exact: bool
    first_divergence: int | None
    divergence_kind: str | None
    stages_matched: int
    detail: str
    stage_report: list[dict]


def _stage_report(truth: list[dict], stages: list[dict]) -> list[dict]:
    report = []
    for i, t in enumerate(truth):
        a = stages[i] if i < len(stages) else {}
        model = a.get("state")
        wrong = ([p for p, (x, y) in enumerate(zip(t["state"], model)) if x != y]
                 + list(range(len(model), len(t["state"])))) if model is not None else None
        report.append({"stage": i + 1, "truth_ran": t["ran"], "truth": t["state"],
                       "model_ran": a.get("ran"), "model": model,
                       "ok": a.get("ran") == t["ran"] and model == t["state"],
                       "wrong_positions": wrong})
    return report


def _truth_stages(question: Question) -> list[dict]:
    """The expected stage log: one entry per trace event, in execution
    order; an edit leaves the list as it was (the prompt says so)."""
    stages, state = [], list(question.start)
    for event in question.trace:
        if isinstance(event, Step):
            state = list(event.seq)
        stages.append({"ran": event.instruction, "state": state})
    return stages


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
        self._truth = _truth_stages(self.question)

    @property
    def observation(self) -> dict:
        """Everything an agent may see. Never includes the answer or trace."""
        q = self.question
        return {
            "spec": str(self.spec),
            "prompt": render_prompt(q.start, q.instructions, q.companions),
            "text": q.text,
            "start": list(q.start),
            "steps": len(q.instructions),
        }

    def submit(self, answer) -> SubmissionResult:
        """Grade a stage log (object or reply text) against the truth."""
        truth, n = self._truth, len(self._truth)

        report: list[dict] = []

        def result(exact, at, kind, matched, detail):
            return SubmissionResult(answer, truth, n, exact, at, kind, matched, detail, report)

        try:
            log = parse_stage_log(answer)
        except MalformedAnswer as e:
            return result(False, 0, "malformed", 0, str(e))

        stages = log["stages"]
        report = _stage_report(truth, stages)
        for i, (t, a) in enumerate(zip(truth, stages), start=1):
            if t["ran"] != a["ran"]:
                return result(False, i, "order", i - 1,
                              f"stage {i}: ran {a['ran']} but {t['ran']} should run next")
            if t["state"] != a["state"]:
                diff = [(p, x, y) for p, (x, y) in enumerate(zip(t["state"], a["state"])) if x != y]
                if len(t["state"]) != len(a["state"]):
                    diff.append(("length", len(t["state"]), len(a["state"])))
                return result(False, i, "state", i - 1,
                              f"stage {i} (instruction {t['ran']}): wrong values "
                              f"(pos, truth, got) {diff}")
        if len(stages) != n:
            at = min(len(stages), n) + 1
            return result(False, at, "count", min(len(stages), n),
                          f"stage count {len(stages)} vs {n}")
        if log["final"] != self.question.final:
            return result(False, n + 1, "final", n,
                          f"final differs: {log['final']} vs {self.question.final}")
        return result(True, None, None, n, "exact")


def make(spec: str) -> QuestionEnvironment:
    """Factory: run spec string -> ready environment (the Arcade analog)."""
    parsed = RunSpec.parse(spec)
    return QuestionEnvironment(parsed, load_config(parsed.config))

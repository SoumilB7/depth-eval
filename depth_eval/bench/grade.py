"""Grading — a model's stage log against the truth, stage by stage.

A pure function of the truth (the released `stages` and `final` of a
question) and the reply, so scoring needs only questions.jsonl, not the
engine. Grading is STAGE BY STAGE (decision 13, ruling 1): a line whose
work is later overwritten still had to be computed, so it still counts.

    first_divergence  1-based index of the first stage the model got wrong,
                      None when exact. divergence_kind names it:
                        order     ran the wrong instruction at that stage
                        state     right instruction, wrong list
                        count     every stage matched but the log stopped
                                  early or ran on (index = first missing or
                                  surplus stage)
                        final     every stage matched, the final list does
                                  not (index = stages + 1)
                        malformed not a stage log at all (index 0)
    stages_matched    stages correct before that point — the depth reached
    stage_report      every true stage side by side with the model's; each
                      stage is judged on its own, so an error a later line
                      overwrote is visible; empty for a malformed answer
"""

from dataclasses import asdict, dataclass

from depth_eval import Question, Step

from .answer import MalformedAnswer, parse_stage_log


@dataclass(frozen=True)
class Grade:
    exact: bool
    first_divergence: int | None
    divergence_kind: str | None
    stages_matched: int
    stages_expected: int
    detail: str
    stage_report: list[dict]

    def as_dict(self) -> dict:
        return asdict(self)


def truth_stages(question: Question) -> list[dict]:
    """The expected stage log: one entry per trace event, in execution
    order; an edit leaves the list as it was (the prompt says so)."""
    stages, state = [], list(question.start)
    for event in question.trace:
        if isinstance(event, Step):
            state = list(event.seq)
        stages.append({"ran": event.instruction, "state": state})
    return stages


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


def grade(truth: list[dict], final: list[int], answer) -> Grade:
    """Grade a reply (the JSON object or the raw reply text)."""
    n = len(truth)
    try:
        log = parse_stage_log(answer)
    except MalformedAnswer as e:
        return Grade(False, 0, "malformed", 0, n, str(e), [])
    stages = log["stages"]
    report = _stage_report(truth, stages)

    def result(exact, at, kind, matched, detail):
        return Grade(exact, at, kind, matched, n, detail, report)

    for i, (t, a) in enumerate(zip(truth, stages), start=1):
        if t["ran"] != a["ran"]:
            return result(False, i, "order", i - 1,
                          f"stage {i}: ran {a['ran']} but {t['ran']} should run next")
        if t["state"] != a["state"]:
            diff = [(p, x, y) for p, (x, y) in enumerate(zip(t["state"], a["state"])) if x != y]
            if len(t["state"]) != len(a["state"]):
                diff.append(("length", len(t["state"]), len(a["state"])))
            return result(False, i, "state", i - 1,
                          f"stage {i} (instruction {t['ran']}): wrong values (pos, truth, got) {diff}")
    if len(stages) != n:
        return result(False, min(len(stages), n) + 1, "count", min(len(stages), n),
                      f"stage count {len(stages)} vs {n}")
    if log["final"] != final:
        return result(False, n + 1, "final", n, f"final differs: {log['final']} vs {final}")
    return result(True, None, None, n, "exact")

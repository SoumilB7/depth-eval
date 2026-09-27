"""bench — the suite, grading, scoring and the reference solver (no network)."""

import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from depth_eval.bench import build as B
from depth_eval.bench.cli import main
from depth_eval.bench.grade import grade
from depth_eval.bench.solver import Solver

IDENTITY = {"id": "default-s5-L10-01", "config": "default", "steps": 5, "length": 10,
            "list_seed": 42, "instruction_seed": 37}


@pytest.fixture(scope="module")
def q():
    return B.question(IDENTITY)


def truth_log(q):
    return {"stages": [dict(s, state=list(s["state"])) for s in q["truth"]["stages"]],
            "final": list(q["truth"]["final"])}


def graded(q, log):
    return grade(q["truth"]["stages"], q["truth"]["final"], log)


def test_suite_is_the_full_surface_with_its_own_seeds():
    s = B.suite()
    assert len(s) == 3 * 4 * 3 * 10 == len({x["id"] for x in s})
    assert len({(x["list_seed"], x["instruction_seed"]) for x in s}) == len(s)


def test_a_question_is_deterministic_and_keeps_measures_out_of_the_prompt(q):
    assert B.question(IDENTITY) == q
    m = q["measures"]
    assert m["chain_depth"] == max(m["chain_depths"]) and len(m["chain_depths"]) == 5
    assert "chain" not in q["prompt"] and "measures" not in q["prompt"]
    assert len(q["truth"]["stages"]) == 5


def test_grading_exact_and_reply_text(q):
    assert graded(q, truth_log(q)).exact
    assert graded(q, "Here you go:\n```json\n" + json.dumps(truth_log(q)) + "\n```").exact
    chatter = "Tracking Touched[2] = {3, 7} and {} as I go.\n```json\n"   # braces before the log
    assert graded(q, chatter + json.dumps(truth_log(q)) + "\n```").exact


def test_grading_names_the_first_divergence_and_reports_every_stage(q):
    log = truth_log(q)
    log["stages"][2]["state"][0] += 1
    g = graded(q, log)
    assert (g.exact, g.first_divergence, g.divergence_kind, g.stages_matched) == (False, 3, "state", 2)
    assert [s["stage"] for s in g.stage_report if not s["ok"]] == [3]
    assert g.stage_report[2]["wrong_positions"] == [0]


def test_grading_order_count_final_malformed(q):
    log = truth_log(q)
    log["stages"][0]["ran"] += 100
    assert graded(q, log).divergence_kind == "order"
    log = truth_log(q)
    log["stages"].pop()
    assert (graded(q, log).divergence_kind, graded(q, log).first_divergence) == ("count", 5)
    log = truth_log(q)
    log["final"][0] += 1
    assert graded(q, log).divergence_kind == "final"
    g = graded(q, "not json")
    assert (g.divergence_kind, g.first_divergence, g.stage_report) == ("malformed", 0, [])


def test_score_grades_a_directory_and_lists_missing_answers(q, tmp_path, capsys):
    other = B.question(IDENTITY | {"id": "default-s5-L10-02", "instruction_seed": 38})
    (tmp_path / "set").mkdir()
    (tmp_path / "set" / "questions.jsonl").write_text(json.dumps(q) + "\n" + json.dumps(other) + "\n")
    (tmp_path / "answers").mkdir()
    (tmp_path / "answers" / f"{q['id']}.txt").write_text(json.dumps(truth_log(q)))
    main(["score", str(tmp_path / "answers"), "--questions", str(tmp_path / "set")])
    summary = json.loads((tmp_path / "results.json").read_text())["summary"]
    assert (summary["exact"], summary["answered"], summary["missing"]) == (1, 1, [other["id"]])
    assert summary["by_chain_depth"]


def message(stop_reason, *content):
    return SimpleNamespace(model="m", stop_reason=stop_reason, stop_details=None, content=list(content),
                           usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def scripted(*replies):
    """A solver whose client plays back `replies` and keeps every request."""
    sent, queue = [], list(replies)

    def stream(**request):
        sent.append(request)
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return nullcontext(SimpleNamespace(get_final_message=lambda: reply))

    return Solver(model="m", client=SimpleNamespace(messages=SimpleNamespace(stream=stream))), sent


def test_solver_gets_the_prompt_and_only_the_calculators():
    solver, sent = scripted(message("end_turn", SimpleNamespace(type="text", text="{}")))
    assert solver.solve("PROMPT") == "{}"
    assert sent[0]["messages"] == [{"role": "user", "content": "PROMPT"}]
    assert [t["name"] for t in sent[0]["tools"]] == ["calculator", "bulk_calculator"]
    assert not ({"system", "tool_choice", "mcp_servers", "container", "fallbacks"} & set(sent[0]))


def test_solver_runs_the_calculators_until_it_answers():
    call = SimpleNamespace(type="tool_use", id="t1", name="bulk_calculator",
                           input={"expression": "n + p", "n": [5, 5]})
    bad = SimpleNamespace(type="tool_use", id="t2", name="calculator", input={"expression": "1/0"})
    solver, sent = scripted(message("tool_use", call, bad),
                            message("end_turn", SimpleNamespace(type="text", text="done")))
    events = []
    assert solver.solve("PROMPT", events.append) == "done"
    assert [(r["content"], r["is_error"]) for r in sent[1]["messages"][-1]["content"]] == [
        ("[5, 6]", False), ("Error: division by zero", True)]
    assert [next(iter(e)) for e in events] == ["call", "tool", "tool", "call"]


def test_an_api_failure_propagates_and_is_never_an_answer():
    solver, _ = scripted(RuntimeError("overloaded"))
    with pytest.raises(RuntimeError):
        solver.solve("PROMPT")


def test_solver_request_fits_each_model():
    new = Solver(model="claude-opus-5", client=object()).request([])
    assert new["thinking"] == {"type": "adaptive"} and new["output_config"] == {"effort": "high"}
    assert new["max_tokens"] == 128000
    old = Solver(model="claude-haiku-4-5", client=object()).request([])
    assert old["thinking"]["type"] == "enabled" and "output_config" not in old
    assert 1024 <= old["thinking"]["budget_tokens"] < old["max_tokens"] == 64000


def test_repeat_and_undo_of_a_change_say_what_they_do():
    from depth_eval import META_VERBS as V, NUMBER_OPS as O, Instruction, MetaInstruction as MI, execute
    from depth_eval.lines import render_question
    chain = [MI(V["cancel"], 6), MI(V["unwind"], 1), MI(V["amplify"], 5), MI(V["mirror"], 3),
             Instruction(O["n + x"], 3), Instruction(O["n + x"], 100)]
    text = render_question(chain)
    assert "it changed no numbers" in text and "so this does nothing" in text
    assert "make that change once more" in text
    assert execute(chain, [0])[0] == [12]              # the doubling happened twice


def test_arena_audit_accepts_only_the_exact_setup():
    from depth_eval.bench.arena import CALCULATORS, audit
    init = {"type": "system", "subtype": "init", "model": "m", "tools": sorted(CALCULATORS),
            "skills": [], "slash_commands": [], "plugins": []}
    call = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "mcp__calc__calculator"}]}}
    assert audit([init, call], "m") is None
    assert "ran on" in audit([init], "other")
    assert "tools were" in audit([init | {"tools": sorted(CALCULATORS) + ["Bash"]}], "m")
    assert "skills" in audit([init | {"skills": ["x"]}], "m")
    bad = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}
    assert "called Bash" in audit([init, bad], "m")
    assert audit([], "m") == "no session header"

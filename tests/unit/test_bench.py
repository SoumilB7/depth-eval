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


def write_set(folder, *questions, version="9.9.9"):
    """A question set on disk, as build writes it: questions.jsonl + manifest."""
    import hashlib
    folder.mkdir()
    data = "".join(json.dumps(x) + "\n" for x in questions).encode()
    (folder / "questions.jsonl").write_bytes(data)
    (folder / "manifest.json").write_text(json.dumps(
        {"name": "depth-eval", "version": version, "sha256": hashlib.sha256(data).hexdigest()}))


def graded(q, log):
    return grade(q["truth"]["stages"], q["truth"]["final"], log)


def test_suite_is_the_full_surface_with_its_own_seeds():
    s = B.suite()
    assert len(s) == len(B.STEPS) * B.SAMPLES == len({x["id"] for x in s})
    assert len({(x["list_seed"], x["instruction_seed"]) for x in s}) == len(s)


def test_a_question_is_deterministic_and_keeps_measures_out_of_the_prompt(q):
    assert B.question(IDENTITY) == q
    m = q["measures"]
    assert m["chain_depth"] == max(m["chain_depths"]) and len(m["chain_depths"]) == 5
    assert m["open_at_once"] >= 0
    assert "chain" not in q["prompt"] and "measures" not in q["prompt"]
    assert len(q["truth"]["stages"]) == 5


def test_open_at_once_counts_results_still_needed():
    from depth_eval import NUMBER_OPS as O
    from depth_eval import Changed, Instruction
    from depth_eval.nomenclature import open_at_once
    # lines 2 and 3 both need line 1's count: after line 1 runs, 2 results are pending, then 1
    assert open_at_once([Instruction(O["n + x"], 1), Instruction(O["n + x"], Changed(1)),
                         Instruction(O["n + x"], Changed(1))]) == 2
    assert open_at_once([Instruction(O["n + x"], 1)]) == 0


def test_grading_exact_and_reply_text(q):
    assert graded(q, truth_log(q)).exact
    assert graded(q, "Here you go:\n```json\n" + json.dumps(truth_log(q)) + "\n```").exact
    chatter = "Tracking Touched[2] = {3, 7} and {} as I go.\n```json\n"   # braces before the log
    assert graded(q, chatter + json.dumps(truth_log(q)) + "\n```").exact
    broken = json.dumps(truth_log(q)).replace('"state": [', '"state": [[', 1)
    assert graded(q, broken).detail == "the stage log is not valid JSON"


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
    write_set(tmp_path / "set", q, other)
    (tmp_path / "answers").mkdir()
    (tmp_path / "answers" / f"{q['id']}.txt").write_text(json.dumps(truth_log(q)))
    main(["score", str(tmp_path / "answers"), "--questions", str(tmp_path / "set")])
    summary = json.loads((tmp_path / "results.json").read_text())["summary"]
    assert (summary["exact"], summary["answered"], summary["missing"]) == (1, 1, [other["id"]])
    assert summary["by_chain_depth"]
    assert summary["questions"]["version"] == "9.9.9" and summary["run"] is None


def test_a_run_carries_its_set_and_is_scored_only_against_it(q, tmp_path):
    from depth_eval.bench.cli import _stamp
    write_set(tmp_path / "set", q)
    write_set(tmp_path / "newer", q | {"prompt": q["prompt"] + " "}, version="9.9.10")
    run = tmp_path / "run"
    (run / "answers").mkdir(parents=True)
    (run / "answers" / f"{q['id']}.txt").write_text(json.dumps(truth_log(q)))
    _stamp(run, B.identity(tmp_path / "set") | {"model": "m", "runner": "arena"})
    with pytest.raises(SystemExit):   # never resumed against another set or model
        _stamp(run, B.identity(tmp_path / "newer") | {"model": "m", "runner": "arena"})
    with pytest.raises(SystemExit):
        _stamp(run, B.identity(tmp_path / "set") | {"model": "other", "runner": "arena"})
    with pytest.raises(SystemExit):   # never scored against another set
        main(["score", str(run / "answers"), "--questions", str(tmp_path / "newer")])
    main(["score", str(run / "answers"), "--questions", str(tmp_path / "set")])
    summary = json.loads((run / "results.json").read_text())["summary"]
    assert summary["run"]["model"] == "m" and summary["questions"]["sha256"] == summary["run"]["sha256"]
    (tmp_path / "set" / "questions.jsonl").write_text("tampered\n")
    with pytest.raises(ValueError):   # a file that no longer matches its manifest
        B.identity(tmp_path / "set")


def test_the_released_set_is_built_from_this_code():
    """Fast guard (verify is the full proof): the released prompts carry the
    rules text in the code, under the code's version."""
    from pathlib import Path

    from depth_eval import __version__
    from depth_eval.lines import CONVENTIONS
    released = Path(__file__).resolve().parents[2] / "benchmark" / "v2"
    assert B.identity(released)["version"] == __version__
    assert all(x["prompt"].startswith(CONVENTIONS) for x in B.load(released / "questions.jsonl"))


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
    from depth_eval import META_VERBS as V
    from depth_eval import NUMBER_OPS as O
    from depth_eval import Instruction, execute
    from depth_eval import MetaInstruction as MI
    from depth_eval.lines import render_question
    chain = [MI(V["cancel"], 6), MI(V["unwind"], 1), MI(V["amplify"], 5), MI(V["mirror"], 3),
             Instruction(O["n + x"], 3), Instruction(O["n + x"], 100)]
    text = render_question(chain)
    assert "it changed no numbers" in text and "so this does nothing" in text
    assert "make that change once more" in text
    assert execute(chain, [0])[0] == [12]              # the doubling happened twice


def test_the_rules_say_what_the_engine_does():
    """Each clause added by the 1.1 and 1.2 wording audits, checked on the engine."""
    from depth_eval import META_VERBS as V
    from depth_eval import NUMBER_OPS as O
    from depth_eval import At, Instruction, execute
    from depth_eval import MetaInstruction as MI
    from depth_eval.application import Application
    from depth_eval.ops.scope import even_at, span, touched, untouched
    def run(chain, start):
        return execute(chain, start)[0]
    # "x minus the number" is its own inverse: flipped, it does the same
    assert run([MI(V["flip"], 2), Instruction(O["-n + x"], 10)], [3]) == [7]
    # a repeat runs the whole line: its selection, times over, and If checked now
    twice_at_0 = Application(extent=span(0, 0), times=2, gate=even_at(1))
    assert run([Instruction(O["n + x"], 1, application=twice_at_0), MI(V["mirror"], 1)], [0, 0]) == [4, 0]
    assert run([Instruction(O["n + x"], 1, application=twice_at_0), Instruction(O["n + x"], 1),
                MI(V["mirror"], 1)], [0, 0]) == [3, 1]
    # ... and nothing if the line is cancelled
    assert run([MI(V["cancel"], 2), Instruction(O["n + x"], 1), MI(V["mirror"], 2), MI(V["negate"], 2)], [0]) == [0]
    # k times over is undone run by run, each run with its own value (1, then 2)
    assert run([Instruction(O["n + x"], At(0), application=Application(times=2)), MI(V["unwind"], 1)],
               [1, 5]) == [1, 5]
    # undoing an undo makes the change again
    assert run([Instruction(O["n + x"], 3), MI(V["unwind"], 1), MI(V["unwind"], 2)], [0]) == [3]
    # positions applied to: none for a line that did nothing; an undo's are those it put back
    assert run([MI(V["cancel"], 2), Instruction(O["n + x"], 1),
                Instruction(O["n + x"], 10, application=Application(extent=untouched(2)))], [0, 0]) == [10, 10]
    assert run([Instruction(O["n + x"], 1, application=Application(extent=span(0, 0))), MI(V["unwind"], 1),
                Instruction(O["n + x"], 10, application=Application(extent=touched(2)))], [0, 0]) == [10, 0]
    # ... and a line that ran applied to its selection even where nothing changed (1.2)
    assert run([Instruction(O["n + x"], 0, application=Application(extent=span(0, 0))),
                Instruction(O["n + x"], 10, application=Application(extent=touched(1)))], [0, 0]) == [10, 0]
    # ... but a move applied only where a value moved: a sort leaving the 2 in place (1.2)
    from depth_eval.lines import MoveInstruction
    from depth_eval.ops.moves import ascending
    assert run([MoveInstruction(ascending(), application=Application(extent=span(0, 2))),
                Instruction(O["n + x"], 10, application=Application(extent=touched(1)))], [3, 2, 1]) == [11, 2, 13]
    # ... counting a position that received an equal value from elsewhere
    from depth_eval.ops.moves import reverse
    assert run([MoveInstruction(reverse()),
                Instruction(O["n + x"], 10, application=Application(extent=touched(1)))], [2, 5, 2]) == [12, 5, 12]
    # the operand of "1 minus the number" is the 1: doubled, 2 minus the number (1.2)
    assert run([MI(V["amplify"], 2), Instruction(O["-n + x"], 1)], [5]) == [-3]
    # a line released by a released line runs right after it, before the next co-waiter (2.0)
    from depth_eval.dag import schedule
    held = [Instruction(O["n + x"], 1, hold_until_after=4), Instruction(O["n + x"], 1, hold_until_after=4),
            Instruction(O["n + x"], 1, hold_until_after=1), Instruction(O["n + x"], 1)]
    assert schedule(held) == [4, 1, 3, 2]
    # a cancelled line still takes its turn and releases what waits on it (2.0)
    chain = [MI(V["cancel"], 3), Instruction(O["n + x"], 1, hold_until_after=3), Instruction(O["n + x"], 10)]
    assert schedule(chain) == [1, 3, 2] and run(chain, [0]) == [1]
    # "uses x" replaces a doubled operand; doubling doubles whatever is in force (2.0)
    assert run([MI(V["amplify"], 3), MI(V["rewrite"], 3, operand=5), Instruction(O["n + x"], 3)], [0]) == [5]
    assert run([MI(V["rewrite"], 3, operand=5), MI(V["amplify"], 3), Instruction(O["n + x"], 3)], [0]) == [10]
    # "the same selection as j" whether or not j's own If held (2.0)
    from depth_eval.ops.scope import changed_more, same_as
    assert run([Instruction(O["n + x"], 0, application=Application(extent=span(0, 0))),
                Instruction(O["n + x"], 5, application=Application(extent=span(1, 1), gate=changed_more(1, 3))),
                Instruction(O["n + x"], 100, application=Application(extent=same_as(2)))], [0, 0, 0]) == [0, 100, 0]
    # an operand given by a "from now on" line is read when the changed line runs (1.2)
    assert run([MI(V["rewrite"], 3, operand=At(0)), Instruction(O["n + x"], 100), Instruction(O["n + x"], 5)],
               [1]) == [202]


def test_arena_audit_accepts_only_the_exact_setup():
    from depth_eval.bench.arena import CALCULATORS, audit
    init = {"type": "system", "subtype": "init", "model": "m", "tools": sorted(CALCULATORS),
            "skills": [], "slash_commands": [], "plugins": []}
    call = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "mcp__calc__calculator"}]}}
    assert audit([init, call], "m") is None
    assert "ran on" in audit([init], "other")
    assert "tools were" in audit([init | {"tools": sorted(CALCULATORS) + ["Bash"]}], "m")
    assert "skills" in audit([init | {"skills": ["x"]}], "m")
    builtin = {"name": "telemetry", "path": "builtin", "source": "telemetry@builtin"}
    assert audit([init | {"plugins": [builtin]}], "m") is None
    assert "plugins" in audit([init | {"plugins": [builtin, {"name": "x", "source": "x@market"}]}], "m")
    bad = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}
    assert "called Bash" in audit([init, bad], "m")
    assert audit([], "m") == "no session header"

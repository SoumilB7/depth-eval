"""Smoke tests for the harness skeleton — the whole pipeline, no network."""

import inspect
import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from harness import AVAILABLE_AGENTS, Agent, Recorder, RunSpec, Scorecard, Swarm, make


@pytest.fixture(autouse=True)
def recordings_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RECORDINGS_DIR", str(tmp_path))
    return tmp_path


SPEC = "default-s5-L10-ls42-is37"


def test_spec_round_trip():
    spec = RunSpec.parse(SPEC)
    assert str(spec) == SPEC
    assert (spec.config, spec.steps, spec.length) == ("default", 5, 10)
    assert (spec.list_seed, spec.instruction_seed) == (42, 37)


def test_spec_rejects_garbage():
    with pytest.raises(ValueError):
        RunSpec.parse("default-s5-L10")


def test_environment_is_deterministic():
    a, b = make(SPEC), make(SPEC)
    assert a.observation == b.observation
    assert a.question.final == b.question.final


def test_observation_never_leaks_the_answer():
    env = make(SPEC)
    assert "final" not in env.observation
    assert "trace" not in env.observation


def truth_log(env):
    """The stage log the prompt asks for, built from the trace."""
    return {"stages": [dict(s) for s in env._truth], "final": list(env.question.final)}


def test_grading_exact():
    env = make(SPEC)
    graded = env.submit(truth_log(env))
    assert graded.exact and graded.first_divergence is None
    assert graded.stages_matched == graded.stages_expected == len(env.question.trace)


def test_stage_report_shows_every_stage():
    env = make("default-s10-L10-ls42-is37")
    truth = env._truth
    log = {"stages": [dict(t, state=list(t["state"])) for t in truth], "final": list(truth[-1]["state"])}
    log["stages"][2]["state"][0] += 1                       # one slip at stage 3, position 0
    r = env.submit(log)
    assert len(r.stage_report) == len(truth)
    bad = [s for s in r.stage_report if not s["ok"]]
    assert [s["stage"] for s in bad] == [3] and bad[0]["wrong_positions"] == [0]
    assert r.stage_report[3]["ok"]                          # later stages still read on their own
    assert env.submit("not json at all").stage_report == []


def test_grading_accepts_reply_text():
    env = make(SPEC)
    text = "Here you go:\n```json\n" + json.dumps(truth_log(env)) + "\n```"
    assert env.submit(text).exact


def test_grading_wrong_state():
    env = make(SPEC)
    log = truth_log(env)
    log["stages"][2]["state"] = [v + 1 for v in log["stages"][2]["state"]]
    graded = env.submit(log)
    assert (graded.first_divergence, graded.divergence_kind) == (3, "state")
    assert graded.stages_matched == 2


def test_grading_wrong_order():
    env = make(SPEC)
    log = truth_log(env)
    log["stages"][1]["ran"] = 99
    graded = env.submit(log)
    assert (graded.first_divergence, graded.divergence_kind) == (2, "order")


def test_grading_short_log():
    env = make(SPEC)
    log = truth_log(env)
    log["stages"] = log["stages"][:2]
    graded = env.submit(log)
    assert (graded.first_divergence, graded.divergence_kind) == (3, "count")
    assert graded.stages_matched == 2


def test_grading_final_only_wrong():
    env = make(SPEC)
    log = truth_log(env)
    log["final"] = [v + 1 for v in log["final"]]
    graded = env.submit(log)
    n = graded.stages_expected
    assert (graded.first_divergence, graded.divergence_kind) == (n + 1, "final")


def test_grading_malformed():
    env = make(SPEC)
    graded = env.submit("no json here")
    assert (graded.first_divergence, graded.divergence_kind) == (0, "malformed")
    assert env.submit({"stages": [{"ran": 1}], "final": []}).divergence_kind == "malformed"


def test_observation_carries_the_prompt():
    env = make(SPEC)
    obs = env.observation
    assert obs["prompt"].startswith("You are given a starting list")
    assert obs["text"] in obs["prompt"]
    assert obs["steps"] == 5


def test_registry_is_explicit():
    assert set(AVAILABLE_AGENTS) == {"random", "reply", "claude"}
    assert "playback" not in AVAILABLE_AGENTS  # resolved by filename, not name


def test_agents_are_blind():
    assert list(inspect.signature(Agent.solve).parameters) == ["self", "observation"]


def test_random_agent_end_to_end(recordings_dir):
    report = Swarm("random", [SPEC], tags=["test"]).main()
    assert (report["runs"], report["graded"]) == (1, 1)
    assert report["scores"][0]["spec"] == SPEC
    written = json.loads((recordings_dir / f"{report['card_id']}.scorecard.json").read_text())
    assert written["graded"] == 1
    assert len(Recorder.list()) == 1


def test_playback_replays_identically(recordings_dir):
    first = Swarm("random", [SPEC]).main()
    recording = Recorder.list()[0]
    replay = Swarm(recording, []).main()
    assert replay["graded"] == 1
    assert replay["scores"][0]["first_divergence"] == first["scores"][0]["first_divergence"]
    assert Recorder.list() == [recording]  # replaying never writes a second recording


class Crash(Agent):
    def solve(self, observation):
        raise RuntimeError("provider blew up")


def test_a_crashed_run_stays_on_the_card(monkeypatch):
    monkeypatch.setitem(AVAILABLE_AGENTS, "crash", Crash)
    report = Swarm("crash", [SPEC]).main()
    assert (report["runs"], report["graded"], report["errors"]) == (1, 0, [SPEC])
    assert report["scores"][0]["error"] == "RuntimeError: provider blew up"


def test_a_run_cut_short_is_unfinished():
    swarm = Swarm("random", [SPEC])
    swarm.scorecard = Scorecard()
    swarm.agents = [AVAILABLE_AGENTS["random"]("card", make(SPEC), "random", record=False)]
    report = swarm.close_scorecard()
    assert (report["graded"], report["unfinished"]) == (0, [SPEC])


def test_reply_agent(recordings_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("ANSWERS_DIR", str(tmp_path))
    reply = tmp_path / f"{SPEC}.txt"
    reply.write_text(json.dumps(truth_log(make(SPEC))))
    assert Swarm("reply", [SPEC]).main()["scores"][0]["exact"]
    reply.write_text("")
    assert Swarm("reply", [SPEC]).main()["scores"][0]["divergence_kind"] == "malformed"
    reply.unlink()
    assert Swarm("reply", [SPEC]).main()["errors"] == [SPEC]


def message(stop_reason, *content):
    return SimpleNamespace(model="m", stop_reason=stop_reason, stop_details=None,
                           content=list(content),
                           usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def scripted_claude(monkeypatch, *replies):
    """A Claude agent whose client plays back `replies` and keeps every request."""
    from harness.templates import Claude

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    agent = Claude("card", make(SPEC), "claude", record=False)
    sent, queue = [], list(replies)

    def stream(**request):
        sent.append(request)
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return nullcontext(SimpleNamespace(get_final_message=lambda: reply))

    agent.client = SimpleNamespace(messages=SimpleNamespace(stream=stream))
    return agent, sent


def test_claude_gets_the_prompt_and_only_the_calculators(monkeypatch):
    agent, sent = scripted_claude(monkeypatch, message("end_turn", SimpleNamespace(type="text", text="{}")))
    agent.main()
    assert sent[0]["messages"] == [{"role": "user", "content": agent.env.observation["prompt"]}]
    assert [t["name"] for t in sent[0]["tools"]] == ["calculator", "bulk_calculator"]
    assert not ({"system", "tool_choice", "mcp_servers", "container", "fallbacks"} & set(sent[0]))


def test_claude_runs_the_calculators_until_it_answers(monkeypatch):
    call = SimpleNamespace(type="tool_use", id="t1", name="bulk_calculator",
                           input={"expression": "n + p", "n": [5, 5]})
    bad = SimpleNamespace(type="tool_use", id="t2", name="calculator", input={"expression": "1/0"})
    answer = json.dumps(truth_log(make(SPEC)))
    agent, sent = scripted_claude(monkeypatch, message("tool_use", call, bad),
                                  message("end_turn", SimpleNamespace(type="text", text=answer)))
    agent.main()
    results = sent[1]["messages"][-1]["content"]
    assert [(r["content"], r["is_error"]) for r in results] == [
        ("[5, 6]", False), ("Error: division by zero", True)]
    assert agent.result.exact


def test_claude_api_failure_is_an_error_not_a_grade(monkeypatch):
    agent, _ = scripted_claude(monkeypatch, RuntimeError("overloaded"))
    agent.main()
    assert (agent.outcome, agent.result) == ("error", None)

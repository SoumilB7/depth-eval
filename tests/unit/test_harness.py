"""Smoke tests for the harness skeleton — the whole pipeline, no network."""

import json

import pytest

from harness import AVAILABLE_AGENTS, Recorder, RunSpec, Swarm, make


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


def test_grading():
    env = make(SPEC)
    right = env.submit(env.question.final)
    assert right.exact and right.first_wrong is None
    wrong = list(env.question.final)
    wrong[3] += 1
    graded = env.submit(wrong)
    assert not graded.exact and graded.first_wrong == 3
    short = env.submit(env.question.final[:4])
    assert not short.exact and short.first_wrong == 4


def test_registry_is_explicit():
    assert "random" in AVAILABLE_AGENTS
    assert "playback" not in AVAILABLE_AGENTS  # resolved by filename, not name


def test_random_agent_end_to_end(recordings_dir):
    report = Swarm("random", [SPEC], tags=["test"]).main()
    assert report["played"] == 1
    assert report["scores"][0]["spec"] == SPEC
    assert (recordings_dir / f"{report['card_id']}.scorecard.json").is_file()
    written = json.loads(
        (recordings_dir / f"{report['card_id']}.scorecard.json").read_text()
    )
    assert written["played"] == 1
    recordings = Recorder.list()
    assert len(recordings) == 1


def test_playback_replays_identically(recordings_dir):
    first = Swarm("random", [SPEC]).main()
    recording = Recorder.list()[0]
    replay = Swarm(recording, []).main()
    assert replay["played"] == 1
    assert replay["scores"][0]["exact"] == first["scores"][0]["exact"]
    assert replay["scores"][0]["first_wrong"] == first["scores"][0]["first_wrong"]
    # replaying never writes a second recording
    assert Recorder.list() == [recording]

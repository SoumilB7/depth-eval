"""generator + configs — determinism, seed separation, nomenclature round-trip."""

import pytest

from depth_eval import GeneratorConfig, classify, generate, list_configs, load_config, make_sequence, make_sequences


def test_every_state_is_deterministic_and_round_trips():
    for state in list_configs():
        cfg = load_config(state)
        a, b = generate(37, 37, 8, 10, cfg), generate(37, 37, 8, 10, cfg)
        assert a.text == b.text and a.final == b.final
        for ins in a.instructions:
            assert classify(ins).category in ("direct", "relative")


def test_seeds_are_separated():
    cfg = load_config("shallow")
    a, b, c = generate(42, 1, 6, 10, cfg), generate(42, 2, 6, 10, cfg), generate(43, 1, 6, 10, cfg)
    assert a.start == b.start and a.text != b.text and c.start != a.start
    lists = make_sequences(42, 7, 10)
    assert lists[0] == make_sequence(42, 10) and a.companions == lists[1:]


def test_steps_and_length_are_run_parameters():
    q = generate(5, 5, 1, 6, load_config("deep"))
    assert len(q.instructions) == 1 and len(q.start) == 6
    with pytest.raises(ValueError):
        GeneratorConfig(direct_weights={"literal": 1})

"""The calculators: the engine's arithmetic, exactly, and nothing else."""

import pytest

from depth_eval import NUMBER_OPS
from depth_eval.bench.calculator import BULK_CALCULATOR, MAX_DIGITS, CalculatorError, evaluate


def outcome(expression, names=None):
    try:
        return evaluate(expression, names)
    except CalculatorError:
        return None


def test_agrees_with_the_engine_on_every_op():
    for op in NUMBER_OPS.values():
        for nv in range(-12, 13):
            for xv in range(-6, 7):
                want = op.apply(nv, xv) if op.defined_for(nv, xv) else None
                assert outcome(str(op.expr), {"n": nv, "x": xv}) == want, (op.id, nv, xv)


@pytest.mark.parametrize("expression", ["7/2", "5//0", "Mod(6, 0)", "2**-1"])
def test_non_integers_and_zero_divisors_are_errors(expression):
    with pytest.raises(CalculatorError):
        evaluate(expression)


@pytest.mark.parametrize("expression", ["__import__('os')", "(1).real", "[1, 2]", "n", "1 if 1 else 2"])
def test_only_arithmetic_is_read(expression):
    with pytest.raises(CalculatorError):
        evaluate(expression)


def test_values_are_bounded():
    with pytest.raises(CalculatorError):
        evaluate(f"10**{MAX_DIGITS + 1}")


def test_bulk_reads_n_p_and_x_per_position():
    assert BULK_CALCULATOR.run({"expression": "Gcd(n, x) + p", "n": [12, 9, 7], "x": [8, 6, 0]}) == "[4, 4, 9]"
    with pytest.raises(CalculatorError):
        BULK_CALCULATOR.run({"expression": "n", "n": [1, 2], "x": [1]})

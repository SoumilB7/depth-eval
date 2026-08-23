"""ops/operands — APPLIER[POSITION] resolution, wording, private lists."""

import pytest

from depth_eval import NUMBER_OPS as O
from depth_eval import At, B, Changed, Instruction, P, POS, START, execute
from depth_eval.ops import position_form

SEQ = [4, 9, 2, 7]
ROWS = [[1, 5, 3, 8]] * 4


def run(operand, op="n + x"):
    return execute([Instruction(O[op], operand)], SEQ, ROWS)[0]


def test_every_applier():
    assert run(At(0)) == [8, 13, 6, 11]              # live, fixed
    assert run(START[P], "n - x") == [0, 0, 0, 0]    # origin, own
    assert run(B[P]) == [5, 14, 5, 15]               # companion, own
    assert run(POS[P]) == [4, 10, 4, 10]             # positional
    assert run(P) == run(POS[P])                     # p == Pos[p]
    assert run(At(P), "x") == SEQ                    # List[p] == n


def test_position_forms():
    assert run(At(At(2))) == [6, 11, 4, 9]           # indirect resolves inside-out
    with pytest.raises(ValueError):                  # offset off the end: no wrap
        run(At(P + 1))
    assert [position_form(i) for i in (3, P, P + 1, At(0))] == [
        "fixed", "own", "offset", "indirect"]


def test_private_list_is_bound_to_its_line():
    rows = [[10, 20, 30], [100, 200, 300]]
    final, trace = execute([Instruction(O["n + x"], B[P]), Instruction(O["n + x"], B[P])],
                           [1, 1, 1], rows)
    assert trace[0].xs == [10, 20, 30] and trace[1].xs == [100, 200, 300]
    with pytest.raises(ValueError):                  # no way to name another line's list
        execute([Instruction(O["n + x"], B[2, 0])], [1, 2], rows)


def test_float_cannot_enter():
    with pytest.raises((TypeError, ValueError)):
        run(2.5)
    with pytest.raises((TypeError, ValueError)):
        execute([Instruction(O["n + x"], 1)], [1.5, 2], ROWS)


def test_wording_one_pattern_per_applier():
    assert O["n + x"].render(At(3)) == "the number plus the number at position 3 of the list (n + List[3])"
    assert O["n + x"].render(START[P]).startswith("the number plus the number at its own position of the starting list")
    assert O["n + x"].render(POS[P]) == "the number plus its own position (n + Pos[p])"
    assert O["n + x"].render(Changed(2)).startswith("the number plus the count of numbers instruction 2 changed")

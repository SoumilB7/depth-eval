"""validation — every error state, detected and blamed."""

from depth_eval import META_VERBS as V
from depth_eval import NUMBER_OPS as O
from depth_eval import At, B, Changed, Instruction, MetaInstruction as MI, P, POS, validate

ROWS = [[1, 2, 3]] * 3


def kinds(chain, start=(1, 2, 3), rows=ROWS):
    return [i.kind for i in validate(chain, list(start), rows)]


def test_structural_kinds():
    assert kinds([Instruction(O["n + x"], 1, hold_until_after=8)]) == ["trigger_out_of_range"]
    assert kinds([Instruction(O["n + x"], 1, hold_until_after=1)]) == ["self_reference"]
    assert set(kinds([Instruction(O["n + x"], 5, hold_until_after=2),
                      Instruction(O["n*x"], 2, hold_until_after=1),
                      Instruction(O["n + x"], Changed(1))])) == {"cycle", "blocked"}


def test_position_kinds():
    assert kinds([Instruction(O["n + x"], At(9))]) == ["position_out_of_range"]
    assert kinds([Instruction(O["n + x"], POS[9])]) == ["position_out_of_range"]
    assert kinds([Instruction(O["n + x"], B[P])], rows=None) == ["companion_required"]
    assert kinds([Instruction(O["n + x"], B[P, 1])]) == ["malformed_operand"]
    assert kinds([Instruction(O["n + x"], At(P + 1))]) == ["undefined_operation"]   # off the end
    assert kinds([Instruction(O["n + x"], At(At(1)))]) == []


def test_meta_kinds():
    assert kinds([Instruction(O["Mod(n, x)"], 2), MI(V["negate"], 1)]) == ["not_invertible"]
    assert kinds([MI(V["cancel"], 3), MI(V["mirror"], 1), Instruction(O["n + x"], 1)]) == ["bad_meta_target"]
    assert kinds([MI(V["rewrite"], 2), Instruction(O["n + x"], 1)]) == ["malformed_operand"]
    assert set(kinds([MI(V["amplify"], 2, hold_until_after=2), Instruction(O["n + x"], 1)])) == {"cycle"}


def test_dynamic_kind_by_trial_run():
    assert kinds([Instruction(O["x"], 0), Instruction(O["Mod(n, x)"], At(1))]) == ["undefined_operation"]
    assert kinds([Instruction(O["n*x"], 3), Instruction(O["n + x"], 1), MI(V["unwind"], 1)],
                 start=(4, 5), rows=[[0, 0]] * 3) == ["undefined_operation"]

"""validation — every error state, detected and blamed."""

from depth_eval import META_VERBS as V
from depth_eval import NUMBER_OPS as O
from depth_eval import (Application, At, B, Changed, Instruction, MetaInstruction as MI, P, POS,
                        START, even_at, span, validate)

ROWS = [[1, 2, 3]] * 3


def kinds(chain, start=(1, 2, 3), rows=ROWS):
    return [i.kind for i in validate(chain, list(start), rows)]


def test_structural_kinds():
    assert kinds([Instruction(O["n + x"], 1, hold_until_after=8)]) == ["trigger_out_of_range"]
    assert kinds([Instruction(O["n + x"], 1, hold_until_after=1)]) == ["self_reference"]
    # holds only point forward, so they can never cycle; a backward hold is dead,
    # and whatever waits on a broken line is blocked
    assert set(kinds([Instruction(O["n + x"], 5),
                      Instruction(O["n*x"], 2, hold_until_after=3),
                      Instruction(O["n + x"], 1, hold_until_after=1)])) == {"dead_hold", "blocked"}


def test_timeline_kinds():
    # only holds move a line: a result used before its line ran, an edit of a line already run
    assert kinds([Instruction(O["n + x"], Changed(2)), Instruction(O["n + x"], 1)]) == ["unexecuted_reference"]
    assert kinds([Instruction(O["n + x"], Changed(2), hold_until_after=2), Instruction(O["n + x"], 1)]) == []
    assert kinds([Instruction(O["n + x"], 1), MI(V["amplify"], 1)]) == ["dead_edit"]
    assert kinds([Instruction(O["n + x"], 1, hold_until_after=2), MI(V["amplify"], 1)]) == []
    assert kinds([MI(V["unwind"], 2), Instruction(O["n + x"], 1)]) == ["unexecuted_reference"]
    # a planted reference is judged at the TARGET's turn (blamed on the editor):
    # rewrite plants Changed[4] into 3; 3 holds until 4 -> order 1,2,4,3 -> legal
    planted = [MI(V["rewrite"], 3, operand=Changed(4)), Instruction(O["n*x"], 2),
               Instruction(O["n + x"], 1, hold_until_after=4), Instruction(O["n - x"], 1)]
    assert kinds(planted, rows=ROWS + [[1, 2, 3]]) == []
    unheld = [MI(V["rewrite"], 3, operand=Changed(4)), Instruction(O["n*x"], 2),
              Instruction(O["n + x"], 1), Instruction(O["n - x"], 1)]
    assert kinds(unheld, rows=ROWS + [[1, 2, 3]]) == ["unexecuted_reference"]


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
    assert kinds([MI(V["amplify"], 2, hold_until_after=2), Instruction(O["n + x"], 1)]) == ["dead_edit"]


def test_dynamic_kind_by_trial_run():
    assert kinds([Instruction(O["n - x"], 1), Instruction(O["Mod(n, x)"], At(0))]) == ["undefined_operation"]
    assert kinds([Instruction(O["n*x"], 3), Instruction(O["n + x"], 1), MI(V["unwind"], 1)],
                 start=(4, 5), rows=[[0, 0]] * 3) == ["undefined_operation"]


def test_information_flow_kinds():
    # a whole-list replace that never reads the live list wipes every earlier line
    assert kinds([Instruction(O["x"], START[P])]) == ["reset"]
    assert kinds([Instruction(O["x"], START[P], application=Application(extent=span(0, 1)))]) == []
    assert kinds([MI(V["rewrite"], 2, operand=7), Instruction(O["x"], At(P))]) == ["reset"]
    # the list after every line keeps the floor of distinct values (2 here)
    assert kinds([Instruction(O["Min(n, x)"], 1)]) == ["collapse"]
    # no-op events are rationed: ceil(0.15 * 3) = 1 allowed, two closed gates is one too many
    closed = Application(gate=even_at(0))  # position 0 holds 1 — never opens
    assert kinds([Instruction(O["n + x"], 1, application=closed)] * 2
                 + [Instruction(O["n + x"], 1)]) == ["too_many_noops"]

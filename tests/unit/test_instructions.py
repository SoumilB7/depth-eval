"""instructions + dag + meta — holds, effect refs, scheduling, the verbs."""

from depth_eval import META_VERBS as V
from depth_eval import NUMBER_OPS as O
from depth_eval import At, B, Changed, EditStep, Instruction, MetaInstruction as MI, execute, schedule


def test_hold_reorders_and_operands_resolve_at_execution():
    chain = [Instruction(O["n + x"], 1), Instruction(O["x"], At(0), hold_until_after=4),
             Instruction(O["n*x"], 2), Instruction(O["n - x"], 2)]
    final, trace = execute(chain, [10, 20, 30])
    assert [s.instruction for s in trace] == [1, 3, 4, 2]
    assert trace[-1].x == 20 and final == [20, 20, 20]


def test_effect_reference_past_and_forward_with_its_hold():
    final, t = execute([Instruction(O["Max(n, x)"], 10), Instruction(O["n + x"], Changed(1))], [3, 12, 7, 20])
    assert t[1].x == 2 and final == [12, 14, 12, 22]
    # a forward result reference carries its own hold — only holds move a line
    chain = [Instruction(O["n + x"], Changed(3), hold_until_after=3), Instruction(O["n*x"], 2),
             Instruction(O["Min(n, x)"], 25)]
    final, t = execute(chain, [5, 10, 20])
    assert [s.instruction for s in t] == [2, 3, 1] and final == [11, 21, 26]


def test_read_verbs():
    assert execute([Instruction(O["n + x"], 5), MI(V["negate"], 1)], [10, 20])[0] == [10, 20]
    final, t = execute([Instruction(O["n + x"], At(0)), MI(V["mirror"], 1)], [1, 2])
    assert t[0].x == 1 and t[1].x == 2 and final == [4, 5]     # re-resolved at its own time


def test_edit_verbs_reorder_target_and_compose():
    final, t = execute([MI(V["amplify"], 2), Instruction(O["n + x"], 3)], [0, 0])
    assert isinstance(t[0], EditStep) and t[0].after == "n + 6" and final == [6, 6]
    assert schedule([Instruction(O["n + x"], 3), MI(V["amplify"], 1)]) == [1, 2]  # an edit never reorders (dead_edit is the validator's call)
    assert execute([MI(V["flip"], 2), Instruction(O["n - x"], 4)], [10])[0] == [14]
    assert execute([MI(V["rewrite"], 2, operand=7), Instruction(O["n*x"], 2)], [3])[0] == [21]
    assert execute([MI(V["amplify"], 3), MI(V["flip"], 3), Instruction(O["n + x"], 5)], [100])[0] == [90]


def test_cancel_is_a_no_op_event():
    chain = [MI(V["cancel"], 2), Instruction(O["n + x"], 5), Instruction(O["n + x"], Changed(2))]
    final, t = execute(chain, [1, 2])
    assert final == [1, 2] and t[1].operation == "(no-op)"


def test_unwind_replays_recorded_x():
    chain = [Instruction(O["n*x"], 3), Instruction(O["n + x"], 3), MI(V["unwind"], 1)]
    final, t = execute(chain, [4, 5])
    assert final == [5, 6] and t[2].xs is None  # replayed values live in the record, not the step
    assert execute([MI(V["cancel"], 2), Instruction(O["n + x"], 5), MI(V["unwind"], 2)], [9])[0] == [9]


def test_rewrite_operand_binds_to_editor_list():
    rows = [[10, 20, 30], [100, 200, 300]]
    assert execute([MI(V["rewrite"], 2, operand=B[0]), Instruction(O["n + x"], 5)], [0], rows)[0] == [10]

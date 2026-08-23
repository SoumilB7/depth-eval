"""nomenclature — DIRECT vs RELATIVE, kinds, types, tags."""

from depth_eval import META_VERBS as V
from depth_eval import NUMBER_OPS as O
from depth_eval import At, B, Changed, Instruction, MetaInstruction as MI, P, POS, START, classify, type_of

CASES = {
    Instruction(O["n + x"], 7):            ("direct.literal", None),
    Instruction(O["n + x"], At(3)):        ("direct.live", "fixed"),
    Instruction(O["n + x"], At(P + 1)):    ("direct.live", "offset"),
    Instruction(O["n + x"], At(At(0))):    ("direct.live", "indirect"),
    Instruction(O["n + x"], START[P]):     ("direct.origin", "own"),
    Instruction(O["n*x"], B[2]):           ("direct.companion", "fixed"),
    Instruction(O["n + x"], POS[P]):       ("direct.positional", "own"),
    Instruction(O["n + x"], At(1) + B[0]): ("direct.composite", None),
    Instruction(O["n + x"], 7, hold_until_after=3): ("direct.literal+held", None),
    Instruction(O["n + x"], Changed(2) + At(0)):    ("relative.consumes.effect", None),
    MI(V["mirror"], 1):                    ("relative.consumes.definition", "mirror"),
    MI(V["unwind"], 1):                    ("relative.consumes.execution", "unwind"),
    MI(V["rewrite"], 1, operand=5):        ("relative.affects.alter", "rewrite"),
    MI(V["cancel"], 1, hold_until_after=4): ("relative.affects.erase+held", "cancel"),
}


def test_labels_and_types():
    for ins, (label, typ) in CASES.items():
        assert (str(classify(ins)), type_of(ins)) == (label, typ)

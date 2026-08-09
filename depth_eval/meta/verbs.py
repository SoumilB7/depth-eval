"""The meta-verb vocabulary. Each verb is a MetaVerb instance.

Semantics (executor is the source of truth, this is the contract):

- mirror j : apply j's CURRENT definition once more, operand re-resolved at
             mirror's own execution time. Mirroring a cancelled j = no-op.
- negate j : apply the INVERSE of j's current op, operand re-resolved now.
             Target's op must be invertible (validated).
- amplify j: edit — j's operand becomes 2×(its operand expression).
- flip j   : edit — j's op becomes its inverse (op must be invertible).
- rewrite j: edit — j's operand becomes this instruction's operand {x}.
- cancel j : edit — j becomes a no-op (it still "executes" as an event, so
             Changed[j] resolves to 0).
- unwind j : apply the inverse of what j ACTUALLY executed, using the exact
             x values j resolved when it ran (from the trace).

Edits compose in execution order. Changed[editor] = 0 (edits touch
definitions, not the list).
"""

from .base import MetaVerb

META_VERBS: dict[str, MetaVerb] = {
    v.name: v
    for v in [
        MetaVerb(
            "mirror", "read",
            "Apply instruction {j}'s operation once more, as it is currently defined",
        ),
        MetaVerb("negate", "read", "Do the opposite of instruction {j}'s operation"),
        MetaVerb("amplify", "edit", "Instruction {j} must use double its operand"),
        MetaVerb("flip", "edit", "Instruction {j} must do the inverse of its operation"),
        MetaVerb(
            "rewrite", "edit",
            "Instruction {j} must use {x} as its operand",
            takes_operand=True,
        ),
        MetaVerb("cancel", "edit", "Instruction {j} must do nothing"),
        MetaVerb("unwind", "undo", "Undo what instruction {j} did"),
    ]
}

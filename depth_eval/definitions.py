"""What a data line currently MEANS — the executor's definitions table.

The listing never changes; edit verbs replace entries here. A definition
knows its own inverse, its amplified and rewritten forms, and its
canonical formula, so verbs are one-line transforms (meta/verbs.py).

Private-list ownership — the rule: B always means the list of the line the
text is written on. A definition's extent and gate were written on the
data line itself (`line`); its operand may have been written elsewhere by
a rewrite (`operand_owner`). Mirror/negate run a definition under another
number but keep both owners, so they read the same lists the target would.
"""

from dataclasses import dataclass, replace

import sympy as sp

from .application import Application
from .ops import NUMBER_OPS
from .ops.base import NumberOp
from .ops.moves import Move


@dataclass(frozen=True)
class MapDef:
    op: NumberOp
    operand: object
    how: Application
    line: int            # owner of B in the extent and gate
    operand_owner: int   # owner of B in the operand (the editor after a rewrite)

    @property
    def name(self) -> str:
        return self.op.id

    def describe(self) -> str:
        return self.how.formula(self.op.formula(self.operand))

    def inverted(self) -> "MapDef | None":
        if self.op.inverse is None:
            return None
        return replace(self, op=NUMBER_OPS[self.op.inverse])

    def amplified(self) -> "MapDef":
        return replace(self, operand=2 * sp.sympify(self.operand))

    def rewritten(self, operand, owner: int) -> "MapDef":
        return replace(self, operand=operand, operand_owner=owner)


@dataclass(frozen=True)
class MoveDef:
    move: Move
    how: Application
    line: int            # owner of B in the extent and gate

    @property
    def name(self) -> str:
        return self.move.name

    def describe(self) -> str:
        return self.how.formula(self.move.formula)

    def inverted(self) -> "MoveDef | None":
        move = self.move.inverse()
        return None if move is None else replace(self, move=move)


def describe(definition) -> str:
    return "(cancelled)" if definition is None else definition.describe()

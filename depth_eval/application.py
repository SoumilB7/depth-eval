"""Application — HOW a line lands on the list.

An instruction is WHAT (op + operand: the direct/relative nomenclature)
× HOW (this). Five orthogonal axes, defaults = the way every line landed
before this type existed:

    EXTENT  which positions     whole | partial (a Scope)
    FORM    what kind of change map (values change) | permute (values move)
    ORDER   how a pass reads    snapshot | forward | backward
    TIMES   how many passes     1 | k
    GATE    does it fire        always | if (a whole-list condition, a Scope
                                with no p — resolved at execution; closed =
                                the line runs as a no-op event, a legal trap)

Declared and executable now: EXTENT, TIMES, GATE. Declared but LOCKED
(validation rejects them until the decision lands): FORM=permute (needs
its own line shape — a permute has no op/operand) and ORDER=forward|
backward (the one axis that changes what "now" means inside a pass; needs
Soumil's explicit yes). Everything composes: "if …, for every 3rd number
from position 2, 3 times, add …" is one line with one meaning.
"""

from dataclasses import dataclass

import sympy as sp

from .ops.scope import ALL, Scope

FORMS = ("map", "permute")
ORDERS = ("snapshot", "forward", "backward")
ENABLED = {"form": ("map",), "order": ("snapshot",)}

ALWAYS = Scope("always", sp.true, "always")

# the drawable pass counts (hand-built lines may use any times >= 1)
TIMES_CHOICES = ("1", "2", "3")


@dataclass(frozen=True)
class Application:
    extent: Scope = ALL
    form: str = "map"
    order: str = "snapshot"
    times: int = 1
    gate: Scope = ALWAYS

    @property
    def marks(self) -> tuple[str, ...]:
        """The non-default axes, for labels: ('stride', 'x3', 'if')."""
        marks = []
        if self.extent is not ALL:
            marks.append(self.extent.kind)
        if self.form != "map":
            marks.append(self.form)
        if self.order != "snapshot":
            marks.append(self.order)
        if self.times != 1:
            marks.append(f"x{self.times}")
        if self.gate is not ALWAYS:
            marks.append("if")
        return tuple(marks)


WHOLE = Application()

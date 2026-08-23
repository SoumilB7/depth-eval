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

All five axes execute (ORDER approved 2026-08-26; FORM=permute is the
MoveInstruction line kind). An ordered pass resolves each element AT ITS
OWN MOMENT — operand and extent test see the already-updated elements
before it (forward: left to right; backward: right to left); the gate is
still checked once, pre-pass; the operand resolves only where the line
applies. Locked still: ordered or scoped moves. Everything composes: "if
…, for every 3rd number from position 2, 3 times, add …, moving left to
right" is one line with one meaning.
"""

from dataclasses import dataclass

import sympy as sp

from .ops.scope import ALL, Scope

FORMS = ("map", "permute")
ORDERS = ("snapshot", "forward", "backward")

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


def locked_reason(how: Application, move: str | None = None) -> str | None:
    """THE single authority on which applications are legal. Returns the
    reason a combination is locked, or None if it may execute.
    `move` is the move name for a permute line, None for a map line."""
    if how.form not in FORMS or how.order not in ORDERS:
        return f"unknown axis value (form={how.form!r}, order={how.order!r})"
    if how.times < 1:
        return "times must be >= 1"
    if how.form != "map":
        return "form is carried by the line kind (MoveInstruction), not this flag"
    if move is not None and how.order != "snapshot":
        return "an ordered move has no meaning — a permutation is simultaneous"
    if move == "swap" and how.extent.kind != "all":
        return "a scoped swap is not allowed — swap already names absolute positions"
    return None

"""The line kinds a question is written in, and how they render.

    DataLine          the shared shape of every line that lands on the list:
                      a hold and an Application (HOW it lands)
      Instruction     a MAP line   — (op, operand): touched values change
      MoveInstruction a PERMUTE line — (move): values move (ops/moves.py)
    MetaInstruction   a verb aimed at another line (meta/base.py)

Rendering: the full sentence in words, then the complete canonical formula
(Application.formula) once, in square brackets. A line whose text reads B
shows its own private list inline, so the question text is self-contained.
"""

from dataclasses import dataclass

from .application import ALWAYS, WHOLE, Application
from .ops.base import NumberOp
from .ops.moves import Move
from .ops.operands import uses_companion
from .ops.scope import ALL


def _with_list(words: str, exprs, companion: list[int] | None) -> str:
    """Append the line's private list when its text reads B."""
    if companion is not None and any(e is not None and uses_companion(e) for e in exprs):
        return f"{words} — this instruction's list B = {list(companion)}"
    return words


def _decorate(words: str, core: str, how: Application, number: int, hold: int | None) -> str:
    """One shape for every data line: words, then [the canonical formula]."""
    if how.order != "snapshot":
        direction = "left to right" if how.order == "forward" else "right to left"
        words = (f"{words}, one number at a time moving {direction} "
                 "(each number sees the numbers already updated before it)")
    if how.times != 1:
        words = f"{words}, {how.times} times over"
    if how.gate is not ALWAYS:
        words = f"If {how.gate.phrase}: {words}"
    body = f"{words} [{how.formula(core)}]"
    if hold is not None:
        return (
            f"{number}. Hold this instruction until instruction "
            f"{hold} has executed, then apply it: {body}"
        )
    return f"{number}. {body}"


@dataclass(frozen=True, kw_only=True)
class DataLine:
    """What every line that lands on the list has: WHEN (a hold) and HOW
    (an Application). hold_until_after is the 1-based number of the line
    that must have executed first, or None."""

    hold_until_after: int | None = None
    application: Application = WHOLE


@dataclass(frozen=True)
class Instruction(DataLine):
    """A map line: apply `op` with `operand` where the application says."""

    op: NumberOp
    operand: object

    def render(self, number: int, companion: list[int] | None = None) -> str:
        how = self.application
        if how.extent is ALL:
            words = f"Replace every number with {self.op.wording(self.operand)}"
        else:
            words = (f"For {how.extent.phrase}, replace it with "
                     f"{self.op.wording(self.operand)}")
        words = _with_list(words, (self.operand, how.extent.where, how.gate.where), companion)
        return _decorate(words, self.op.formula(self.operand), how, number,
                         self.hold_until_after)


@dataclass(frozen=True)
class MoveInstruction(DataLine):
    """A permute line: values move as `move` says."""

    move: Move

    def render(self, number: int, companion: list[int] | None = None) -> str:
        how = self.application
        if how.extent is ALL:
            words = self.move.phrase
        else:
            words = (f"{self.move.phrase}, but only {how.extent.phrase}, "
                     "keeping everything else in place")
        words = _with_list(words, (how.extent.where, how.gate.where), companion)
        return _decorate(words, self.move.formula, how, number, self.hold_until_after)


def render_question(instructions: list, companions: list[list[int]] | None = None) -> str:
    """The numbered question text; with companions, private lists inline."""
    lines = []
    for i, ins in enumerate(instructions, start=1):
        companion = companions[i - 1] if companions is not None else None
        lines.append(ins.render(i, companion))
    return "\n".join(lines)

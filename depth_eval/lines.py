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
        words = f"{words}, {how.times} times over (re-reading every reference each time)"
    if how.gate is not ALWAYS:
        words = f"If {how.gate.phrase}: {words}"
    body = f"{words} [{how.formula(core)}]"
    if hold is not None:
        return (
            f"{number}. Hold this instruction until instruction "
            f"{hold} has executed, then apply it immediately after it: {body}"
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
            words = (f"For {how.extent.phrase}, replace each of them with "
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


CONVENTIONS = """\
You are given a starting list of integers and a numbered list of instructions. Apply the instructions by careful reasoning only and report the list after every one. Each instruction says exactly what it does; these are the only rules that live outside the lines.

- Positions count from 0. "The number at position i of the list" is the value there at the moment the instruction runs; "the starting list" is the list before anything ran; "this instruction's list B" is the private list printed on that line; "its own position" is the position of the number being replaced.
- Instructions run in numbered order, each exactly once. A line that says "hold this instruction until instruction k has executed" skips its turn and runs immediately after k. If several lines are waiting on the same k they run in listing order, and anything they in turn release runs right after them in the same way.
- An instruction reads the list as it is right before it runs (one snapshot) and replaces all its selected numbers at once — except a line marked "one number at a time", which updates positions in the stated direction and re-reads the list for each number. "If <condition>:" is checked once, before the line runs; when it fails the line does nothing. "k times over" runs the whole line k times in a row, re-reading every reference each time (the condition is not re-checked).
- "The count of numbers instruction j changed" is how many positions held a different value after instruction j than before it — the whole line, all its times over. A line that does nothing (cancelled, failed condition, an undo of nothing, or a "from now on" line) changed 0. "Positions instruction j applied to" are the positions its selection covered when it ran (for a move: the positions whose value moved). "The same selection as instruction j" applies j's current selection rule to the list now.
- "From now on, instruction j ..." changes what j does when its turn comes; such changes stack in the order they run, and a cancelled line stays cancelled. "As it is currently defined" includes every such change so far. The inverse of an operation: plus ↔ minus, times ↔ divided exactly, reverse ↔ reverse, rotate right by k ↔ rotate left by k, swap ↔ the same swap. "Undo what instruction j actually did" applies the inverse with the exact values j used, at the positions j applied to (for a move: puts the values back the way j moved them), to the list as it is now.
- Everything stays an integer; negative numbers are allowed. "Rounded down" is toward minus infinity (−7 divided by 2, rounded down, is −4). "The remainder when a is divided by b" takes the sign of b (the remainder when −7 is divided by 3 is 2). gcd and lcm are never negative; gcd(a, 0) = |a| and lcm(a, 0) = 0. "Divided exactly" always divides without remainder. "Rotate the list right by k" moves every value k positions to the right, wrapping around to the front.
- The formula in square brackets at the end of a line says the same thing exactly: n is the number being replaced and p its position; List[i], Start[i], B[i] are the value at position i of the current list, the starting list and the line's private list; Pos[p] is the position itself; Changed[j] is the count instruction j changed; Touched[j, p] is 1 where instruction j applied to position p; ScopeOf[j] is instruction j's current selection rule; "where" gives the selection, "if" the condition, "xK" the times over, "forward"/"backward" the one-at-a-time direction; floor rounds down, Mod is the remainder.

ANSWER: reply with one JSON object and nothing else —
{"stages": [{"ran": <instruction number>, "state": [<the whole list after it>]}, ...], "final": [<the final list>]}
one entry per instruction, in the order they ran; a line that did nothing still gets an entry with the unchanged list.
"""


def render_prompt(start: list[int], instructions: list,
                  companions: list[list[int]] | None = None) -> str:
    """The complete text a model is given: conventions, start, numbered lines."""
    return (f"{CONVENTIONS}\nStarting list: {list(start)}\n\nInstructions:\n"
            f"{render_question(instructions, companions)}\n")

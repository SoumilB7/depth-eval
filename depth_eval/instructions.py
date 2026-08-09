"""Instruction chains and their execution (pass 3 of the solver).

An Instruction is one line of a question: an operation with an operand,
optionally HELD — "execute this only after instruction #k has executed".
Effect references in an operand (Changed(j)) hold implicitly, with no hold
clause. Ordering itself is decided statically in dag.schedule(); execution
here just replays that schedule against the data.

Operands resolve at EXECUTION time: At(p) reads the list as it stands when
the instruction actually runs — never the state at its listed position —
and Changed(j) reads instruction j's latest execution.

The trace is event-based: one Step per execution event. Instructions
currently execute once each, but repeats (an instruction executing again)
are an allowed future feature — effect references always mean the LATEST
execution of their target.
"""

from dataclasses import dataclass

from .dag import schedule
from .ops.base import NumberOp
from .ops.operands import is_elementwise, resolve_elementwise


@dataclass(frozen=True)
class Instruction:
    """One line: apply `op` with `operand` (int or operand expression).

    hold_until_after: 1-based number of the instruction that must have
    executed first, or None to execute at its listed position.
    """

    op: NumberOp
    operand: object
    hold_until_after: int | None = None

    def render(self, number: int) -> str:
        body = f"Replace every number with {self.op.render(self.operand)}"
        if self.hold_until_after is not None:
            return (
                f"{number}. Hold this instruction until instruction "
                f"{self.hold_until_after} has executed, then apply it: {body}"
            )
        return f"{number}. {body}"


@dataclass(frozen=True)
class Step:
    """One execution event in the trace."""

    instruction: int      # 1-based listing number
    x: int | None         # resolved operand value; None for per-element operands
    xs: list[int] | None  # the resolved vector for per-element operands
    operation: str        # exact operation applied, formula render ("-n - 78")
    words: str            # exact operation applied, worded ("-78 minus the number")
    changed: int          # count of positions whose value changed
    seq: list[int]        # list state after this event


def render_question(instructions: list[Instruction]) -> str:
    return "\n".join(ins.render(i) for i, ins in enumerate(instructions, start=1))


def execute(
    instructions: list[Instruction],
    start: list[int],
    companions: list[list[int]] | None = None,
) -> tuple[list[int], list[Step]]:
    """Run a chain in its scheduled order. Returns (final list, trace).

    companions[k-1] is instruction k's frozen list B[k] (all rows from the
    list seed's stream at fixed offsets); required only when referenced.
    """
    order = schedule(instructions)
    seq = list(start)
    original = list(start)  # frozen — what Start[i] reads
    effects: dict[int, int] = {}
    trace: list[Step] = []

    for number in order:
        ins = instructions[number - 1]
        per_element = is_elementwise(ins.operand)
        try:
            xs = resolve_elementwise(ins.operand, seq, effects, companions, original)
            new = [ins.op.apply(v, xv) for v, xv in zip(seq, xs)]
        except ValueError as e:
            error = ValueError(f"instruction {number}: {e}")
            error.instruction = number
            raise error from e
        changed = sum(1 for old, now in zip(seq, new) if old != now)
        seq = new
        effects[number] = changed
        if per_element:
            step = Step(number, None, xs, ins.op.formula(ins.operand),
                        ins.op.wording(ins.operand), changed, list(seq))
        else:
            step = Step(number, xs[0], None, ins.op.formula(xs[0]),
                        ins.op.wording(xs[0]), changed, list(seq))
        trace.append(step)

    return seq, trace

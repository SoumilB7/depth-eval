"""Instruction chains and their execution.

An Instruction is one line of a question: an operation with an operand,
optionally HELD — "execute this only after instruction #k has executed".
A held instruction parks until its trigger runs, then executes immediately
after it. Several instructions parked on the same trigger keep their listed
order; releases cascade (a released instruction can itself be a trigger).

Operands resolve at EXECUTION time: At(p) reads the list as it stands when
the instruction actually runs — never the state at its listed position.

Unsatisfiable holds (self-hold, circular holds, trigger out of range) leave
instructions permanently parked; execute() raises on them, and the question
generator must never emit such a chain.
"""

from dataclasses import dataclass

from .ops.base import NumberOp
from .ops.operands import resolve


@dataclass(frozen=True)
class Instruction:
    """One line: apply `op` with `operand` (int or operand expression).

    hold_until_after: 1-indexed number of the instruction that must have
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
    """One executed instruction in the trace."""

    instruction: int  # 1-indexed listing number
    x: int            # the operand's resolved value at execution time
    seq: list[int]    # list state after this instruction


def render_question(instructions: list[Instruction]) -> str:
    return "\n".join(ins.render(i) for i, ins in enumerate(instructions, start=1))


def execute(instructions: list[Instruction], start: list[int]) -> tuple[list[int], list[Step]]:
    """Run a chain, honouring holds. Returns (final list, ordered trace)."""
    seq = list(start)
    executed: set[int] = set()
    parked: dict[int, list[int]] = {}
    trace: list[Step] = []

    def run(number: int) -> None:
        ins = instructions[number - 1]
        x = resolve(ins.operand, seq)
        seq[:] = [ins.op.apply(v, x) for v in seq]
        executed.add(number)
        trace.append(Step(number, x, list(seq)))
        for waiting in parked.pop(number, []):
            run(waiting)

    for number, ins in enumerate(instructions, start=1):
        trigger = ins.hold_until_after
        if trigger is not None and trigger not in executed:
            parked.setdefault(trigger, []).append(number)
        else:
            run(number)

    if parked:
        stuck = sorted(number for waiting in parked.values() for number in waiting)
        raise ValueError(f"instructions {stuck} never executed (bad or circular holds)")
    return seq, trace

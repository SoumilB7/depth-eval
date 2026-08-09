"""Instruction chains and their execution (pass 3 of the solver).

A chain mixes two kinds of lines:
- Instruction     — a data instruction: (op, operand, optional hold).
- MetaInstruction — a verb aimed at another instruction (mirror, negate,
  amplify, flip, rewrite, cancel, unwind). See meta/verbs.py for the
  contract; ordering effects live in dag.py.

Execution keeps a DEFINITIONS table: it starts as the listing and edit
verbs mutate it (never the listing itself). Apply-events always execute the
CURRENT definition, so the trace records what an instruction became, not
just what it said. A cancelled instruction still executes as an event (a
no-op Step), so Changed[j] on it cleanly resolves to 0.

Operands resolve at EXECUTION time; unwind is the one deliberate exception
— it replays the exact x values its target used, from the execution record.

The trace is event-based: Step for applications (including no-ops),
EditStep for definition changes.
"""

from dataclasses import dataclass

import sympy as sp

from .dag import schedule
from .meta.base import MetaInstruction
from .ops import NUMBER_OPS
from .ops.base import NumberOp
from .ops.operands import is_elementwise, resolve_elementwise


@dataclass(frozen=True)
class Instruction:
    """One data line: apply `op` with `operand` (int or operand expression).

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
    """One application event in the trace (including no-ops)."""

    instruction: int      # 1-based listing number
    x: int | None         # resolved operand value; None for per-element/no-op
    xs: list[int] | None  # the resolved vector for per-element operands
    operation: str        # exact operation applied, formula render ("-n - 78")
    words: str            # exact operation applied, worded ("-78 minus the number")
    changed: int          # count of positions whose value changed
    seq: list[int]        # list state after this event


@dataclass(frozen=True)
class EditStep:
    """One definition change in the trace. The list itself is untouched."""

    instruction: int  # the editor
    target: int
    before: str       # target's definition before, formula render
    after: str        # ... and after ("(cancelled)" for cancel)


def render_question(instructions: list) -> str:
    return "\n".join(ins.render(i) for i, ins in enumerate(instructions, start=1))


def _describe(definition) -> str:
    if definition is None:
        return "(cancelled)"
    op, operand = definition
    return op.formula(operand)


def execute(
    instructions: list,
    start: list[int],
    companions: list[list[int]] | None = None,
) -> tuple[list[int], list]:
    """Run a chain in its scheduled order. Returns (final list, trace).

    companions[k-1] is instruction k's frozen list B[k] (all rows from the
    list seed's stream at fixed offsets); required only when referenced.
    """
    order = schedule(instructions)
    seq = list(start)
    original = list(start)  # frozen — what Start[i] reads
    effects: dict[int, int] = {}
    trace: list = []
    # what each data instruction currently MEANS (edits mutate this table,
    # never the listing)
    definitions: dict[int, tuple[NumberOp, object] | None] = {
        n: (ins.op, ins.operand)
        for n, ins in enumerate(instructions, start=1)
        if isinstance(ins, Instruction)
    }
    # what actually ran: number -> (op, xs), or None for no-ops/edits
    executed: dict[int, tuple[NumberOp, list[int]] | None] = {}

    def run_op(number: int, op: NumberOp, operand) -> None:
        nonlocal seq
        per_element = is_elementwise(operand)
        xs = resolve_elementwise(operand, seq, effects, companions, original)
        new = [op.apply(v, xv) for v, xv in zip(seq, xs)]
        changed = sum(1 for old, now in zip(seq, new) if old != now)
        seq = new
        effects[number] = changed
        executed[number] = (op, xs)
        if per_element:
            trace.append(Step(number, None, xs, op.formula(operand),
                              op.wording(operand), changed, list(seq)))
        else:
            trace.append(Step(number, xs[0], None, op.formula(xs[0]),
                              op.wording(xs[0]), changed, list(seq)))

    def run_noop(number: int, why: str) -> None:
        effects[number] = 0
        executed[number] = None
        trace.append(Step(number, None, None, "(no-op)", why, 0, list(seq)))

    def run_unwind(number: int, target: int) -> None:
        nonlocal seq
        record = executed.get(target)
        if record is None:
            run_noop(number, f"nothing to undo — instruction {target} did nothing")
            return
        op, xs = record
        if op.inverse is None:
            raise ValueError(f"cannot undo {op.id} — it has no inverse")
        inverse = NUMBER_OPS[op.inverse]
        new = [inverse.apply(v, xv) for v, xv in zip(seq, xs)]
        changed = sum(1 for old, now in zip(seq, new) if old != now)
        seq = new
        effects[number] = changed
        executed[number] = (inverse, xs)
        trace.append(Step(number, None, xs, f"undo of instruction {target}",
                          f"undo what instruction {target} did", changed, list(seq)))

    for number in order:
        ins = instructions[number - 1]
        try:
            if isinstance(ins, Instruction):
                definition = definitions[number]
                if definition is None:
                    run_noop(number, "cancelled — do nothing")
                else:
                    run_op(number, *definition)
                continue

            verb = ins.verb
            if verb.klass == "edit":
                before = _describe(definitions.get(ins.target))
                target_def = definitions.get(ins.target)
                if verb.name == "cancel":
                    definitions[ins.target] = None
                elif target_def is not None:
                    op, operand = target_def
                    if verb.name == "amplify":
                        definitions[ins.target] = (op, 2 * sp.sympify(operand))
                    elif verb.name == "flip":
                        if op.inverse is None:
                            raise ValueError(f"cannot flip {op.id} — it has no inverse")
                        definitions[ins.target] = (NUMBER_OPS[op.inverse], operand)
                    elif verb.name == "rewrite":
                        definitions[ins.target] = (op, ins.operand)
                effects[number] = 0
                executed[number] = None
                trace.append(EditStep(number, ins.target, before,
                                      _describe(definitions.get(ins.target))))
            elif verb.klass == "read":
                definition = definitions.get(ins.target)
                if definition is None:
                    run_noop(number,
                             f"instruction {ins.target} is cancelled — nothing to {verb.name}")
                elif verb.name == "mirror":
                    run_op(number, *definition)
                else:  # negate
                    op, operand = definition
                    if op.inverse is None:
                        raise ValueError(f"cannot negate {op.id} — it has no inverse")
                    run_op(number, NUMBER_OPS[op.inverse], operand)
            else:  # undo klass
                run_unwind(number, ins.target)
        except ValueError as e:
            error = ValueError(f"instruction {number}: {e}")
            error.instruction = number
            raise error from e

    return seq, trace

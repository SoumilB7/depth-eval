"""Execution — pass 3 of the solver. The line kinds live in lines.py, what
they currently mean in definitions.py, the verbs in meta/verbs.py; this
module only runs a chain in its scheduled order.

Execution keeps a DEFINITIONS table (MapDef | MoveDef | None-if-cancelled)
that starts as the listing; edit verbs replace entries, the listing never
changes. Apply-events always execute the CURRENT definition, so the trace
records what a line became, not just what it said. A cancelled line still
executes as an event (a no-op Step), so Changed[j] resolves to 0 and
Touched[j, p] to 0 everywhere.

A line's APPLICATION decides how it lands: EXTENT (which positions;
selecting nothing — or a move moving nothing — is a dead line,
empty_scope), TIMES (k passes, everything re-resolved per pass, one trace
event, Changed = the NET change over the whole line), GATE (a whole-list
test, checked once pre-pass; closed = a no-op event), ORDER (an ordered
pass resolves each element at its own moment and its operand only where
it applies).

Operands and scopes resolve at EXECUTION time; unwind is the one deliberate
exception — it replays the execution RECORD: a map line's exact x values on
the exact touched positions, pass by pass in reverse; a move line's
permutation, inverted (so even sort can be unwound).

The trace is event-based: Step for applications (including no-ops),
EditStep for definition changes. Errors are ExecutionError(instruction,
kind): the gate (validation.py) reads both fields.
"""

from dataclasses import dataclass

import sympy as sp

from .application import Application
from .dag import schedule
from .definitions import MapDef, MoveDef, describe
from .lines import Instruction, MoveInstruction
from .meta.base import MetaInstruction
from .ops import NUMBER_OPS
from .ops.base import NumberOp
from .ops.operands import (
    P,
    SCOPE_OF,
    Effect,
    is_elementwise,
    resolve,
    resolve_condition,
    resolve_elementwise,
    resolve_mask,
)
from .ops.scope import ALL


class ExecutionError(ValueError):
    """A chain failed at one instruction: which, and (if named) why."""

    def __init__(self, instruction: int, message: str, kind: str | None = None):
        super().__init__(f"instruction {instruction}: {message}")
        self.instruction = instruction
        self.kind = kind


class Dead(ValueError):
    """A line that would touch nothing — reported as empty_scope."""

    kind = "empty_scope"


@dataclass(frozen=True)
class Step:
    """One application event in the trace (including no-ops)."""

    instruction: int      # 1-based listing number
    x: int | None         # resolved operand value; None for per-element/move/no-op
    xs: list[int] | None  # the resolved vector for per-element operands
    operation: str        # the canonical formula that ran (Application.formula)
    words: str            # the same, worded
    changed: int          # NET count of positions whose value changed
    seq: list[int]        # list state after this event


@dataclass(frozen=True)
class EditStep:
    """One definition change in the trace. The list itself is untouched."""

    instruction: int  # the editor
    target: int
    before: str       # target's definition before, canonical formula
    after: str        # ... and after ("(cancelled)" for cancel)


@dataclass(frozen=True)
class MapRecord:
    """What a map line actually ran: its op and, per pass, the resolved xs
    and the touched mask. undo() inverts every pass in reverse order."""

    op: NumberOp
    passes: tuple  # ((xs, mask), ...)

    def undo(self, seq: list[int]) -> tuple[list[int], list[bool]]:
        if self.op.inverse is None:
            raise ValueError(f"cannot undo {self.op.id} — it has no inverse")
        inverse = NUMBER_OPS[self.op.inverse]
        for xs, mask in reversed(self.passes):
            seq = [inverse.apply(v, xv) if m else v for v, xv, m in zip(seq, xs, mask)]
        return seq, [any(mask[i] for _, mask in self.passes) for i in range(len(seq))]


@dataclass(frozen=True)
class MoveRecord:
    """What a move line actually ran: its composed permutation."""

    permutation: tuple

    def undo(self, seq: list[int]) -> tuple[list[int], list[bool]]:
        inverse = [0] * len(self.permutation)
        for i, s in enumerate(self.permutation):
            inverse[s] = i
        return ([seq[inverse[i]] for i in range(len(seq))],
                [self.permutation[i] != i for i in range(len(seq))])


def execute(
    instructions: list,
    start: list[int],
    companions: list[list[int]] | None = None,
) -> tuple[list[int], list]:
    """Run a chain in its scheduled order. Returns (final list, trace).

    companions[k-1] is instruction k's private list B; required only when a
    line's text reads B.
    """
    order = schedule(instructions)
    seq = list(start)
    original = list(start)  # frozen — what Start[i] reads
    effects: dict[int, Effect] = {}
    trace: list = []
    nothing = Effect(0, (False,) * len(seq))
    definitions: dict[int, MapDef | MoveDef | None] = {}
    for n, ins in enumerate(instructions, start=1):
        if isinstance(ins, Instruction):
            definitions[n] = MapDef(ins.op, ins.operand, ins.application, n, n)
        elif isinstance(ins, MoveInstruction):
            definitions[n] = MoveDef(ins.move, ins.application, n)
    executed: dict[int, MapRecord | MoveRecord | None] = {}

    def list_of(owner: int) -> list[int] | None:
        return companions[owner - 1] if companions is not None else None

    def current_scope(where):
        """ScopeOf[j] -> j's current scope, until none remain."""
        for _ in range(16):
            refs = [r for r in sp.sympify(where).atoms(sp.Indexed) if r.base == SCOPE_OF]
            if not refs:
                return where
            replacements = {}
            for r in refs:
                definition = definitions.get(int(r.indices[0]))
                replacements[r] = definition.how.extent.where if definition else sp.false
            where = where.xreplace(replacements)
        raise ValueError("scope references never settle")

    def gate_open(how: Application, companion) -> bool:
        return resolve_condition(how.gate.where, seq, effects, companion, original)

    def record(number: int, before: list[int], mask, rec, x, xs, operation: str, words: str) -> None:
        changed = sum(1 for old, now in zip(before, seq) if old != now)
        effects[number] = Effect(changed, tuple(mask))
        executed[number] = rec
        trace.append(Step(number, x, xs, operation, words, changed, list(seq)))

    def run_map(number: int, d: MapDef) -> None:
        nonlocal seq
        line_list, operand_list = list_of(d.line), list_of(d.operand_owner)
        if not gate_open(d.how, line_list):
            run_noop(number, f"gate closed — {d.how.gate.phrase} does not hold")
            return
        per_element = is_elementwise(d.operand) or d.how.order != "snapshot"
        before = seq
        where_expr = current_scope(d.how.extent.where)
        passes = []
        for _ in range(d.how.times):  # operands and extent re-resolve every pass
            if d.how.order == "snapshot":
                xs = resolve_elementwise(d.operand, seq, effects, operand_list, original)
                mask = resolve_mask(where_expr, seq, effects, line_list, original)
                if any(mask):
                    seq = [d.op.apply(v, xv) if m else v for v, xv, m in zip(seq, xs, mask)]
            else:
                # ordered pass: each element at its own moment — operand and
                # extent test see the already-updated elements before it,
                # and the operand resolves only where the line applies
                positions = range(len(seq)) if d.how.order == "forward" else range(len(seq) - 1, -1, -1)
                seq = list(seq)
                xs, mask = [0] * len(seq), [False] * len(seq)
                for i in positions:
                    if not resolve_condition(sp.sympify(where_expr).subs(P, i),
                                             seq, effects, line_list, original):
                        continue
                    xs[i] = resolve(sp.sympify(d.operand).subs(P, i),
                                    seq, effects, operand_list, original)
                    seq[i] = d.op.apply(seq[i], xs[i])
                    mask[i] = True
            if not any(mask):
                raise Dead("scope selects no number")
            passes.append((xs, mask))
        core = d.op.formula(d.operand) if per_element else d.op.formula(xs[0])
        words = d.op.wording(d.operand) if per_element else d.op.wording(xs[0])
        touched = [any(m[i] for _, m in passes) for i in range(len(seq))]
        record(number, before, touched, MapRecord(d.op, tuple(passes)),
               None if per_element else xs[0], xs if per_element else None,
               d.how.formula(core), words)

    def run_move(number: int, d: MoveDef) -> None:
        nonlocal seq
        line_list = list_of(d.line)
        if not gate_open(d.how, line_list):
            run_noop(number, f"gate closed — {d.how.gate.phrase} does not hold")
            return
        before = seq
        total = list(range(len(seq)))  # composed permutation across passes
        for _ in range(d.how.times):
            if d.how.extent is ALL:
                sigma = d.move.sigma(seq)
            else:
                # scoped move: permute the values among the selected
                # positions only (the subsequence, in index order)
                selected = resolve_mask(current_scope(d.how.extent.where),
                                        seq, effects, line_list, original)
                chosen = [i for i, m in enumerate(selected) if m]
                sub_sigma = d.move.sigma([seq[i] for i in chosen])
                sigma = list(range(len(seq)))
                for j, i in enumerate(chosen):
                    sigma[i] = chosen[sub_sigma[j]]
            seq = [seq[sigma[i]] for i in range(len(seq))]
            total = [total[sigma[i]] for i in range(len(seq))]
        if all(total[i] == i for i in range(len(seq))):
            raise Dead("the move moves nothing")
        record(number, before, [total[i] != i for i in range(len(seq))],
               MoveRecord(tuple(total)), None, None, d.how.formula(d.move.formula),
               d.move.phrase)

    def run_noop(number: int, why: str) -> None:
        effects[number] = nothing
        executed[number] = None
        trace.append(Step(number, None, None, "(no-op)", why, 0, list(seq)))

    def run_unwind(number: int, target: int) -> None:
        nonlocal seq
        rec = executed.get(target)
        if rec is None:
            run_noop(number, f"nothing to undo — instruction {target} did nothing")
            return
        before = seq
        seq, mask = rec.undo(seq)
        record(number, before, mask, None, None, None,
               f"undo of instruction {target}", f"undo what instruction {target} did")

    def run_definition(number: int, definition) -> None:
        if definition is None:
            run_noop(number, "cancelled — do nothing")
        elif isinstance(definition, MoveDef):
            run_move(number, definition)
        else:
            run_map(number, definition)

    for number in order:
        ins = instructions[number - 1]
        try:
            if not isinstance(ins, MetaInstruction):
                run_definition(number, definitions[number])
                continue
            verb, target = ins.verb, definitions.get(ins.target)
            if verb.klass == "edit":
                new = None if target is None else verb.transform(target, ins, number)
                definitions[ins.target] = new
                effects[number] = nothing
                executed[number] = None
                trace.append(EditStep(number, ins.target, describe(target), describe(new)))
            elif verb.klass == "read":
                if target is None:
                    run_noop(number,
                             f"instruction {ins.target} is cancelled — nothing to {verb.name}")
                else:
                    run_definition(number, verb.transform(target, ins, number))
            else:  # undo
                run_unwind(number, ins.target)
        except ExecutionError:
            raise
        except ValueError as e:
            raise ExecutionError(number, str(e), getattr(e, "kind", None)) from e

    return seq, trace

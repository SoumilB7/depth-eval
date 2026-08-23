"""Instruction chains and their execution (pass 3 of the solver).

A chain mixes two kinds of lines:
- Instruction     — a data instruction: (op, operand, optional hold,
  application — HOW it lands on the list, see application.py).
- MetaInstruction — a verb aimed at another instruction (mirror, negate,
  amplify, flip, rewrite, cancel, unwind). See meta/verbs.py for the
  contract; ordering effects live in dag.py.

A line's APPLICATION decides how it lands: its EXTENT (a Scope — which
positions; ALL by default; selecting nothing is an error, empty_scope),
its TIMES (k passes, operands re-resolved every pass, one trace event for
the whole), and its GATE (a whole-list condition; closed = a no-op event).

Every line may carry a private list B (its companion). B in an operand,
scope, or gate always means the list of the LINE THE TEXT IS WRITTEN ON —
so a definition is (op, operand, application, owner) where owner is the
line whose list B refers to. A data line owns its own definition; a rewrite installs
an operand written on the editor's line, so that definition's owner is the
editor; mirror/negate execute j's definition (application included) and so read
j's list. Nothing can name another line's list explicitly.

Execution keeps a DEFINITIONS table: it starts as the listing and edit
verbs mutate it (never the listing itself). Apply-events always execute the
CURRENT definition, so the trace records what an instruction became, not
just what it said. A cancelled instruction still executes as an event (a
no-op Step), so Changed[j] on it cleanly resolves to 0 and Touched[j, p]
to 0 everywhere.

Operands and scopes resolve at EXECUTION time; unwind is the one deliberate
exception — it replays the exact x values its target used, on the exact
positions it touched, from the execution record.

The trace is event-based: Step for applications (including no-ops),
EditStep for definition changes.
"""

from dataclasses import dataclass

import sympy as sp

from .dag import schedule
from .meta.base import MetaInstruction
from .ops import NUMBER_OPS
from .ops.base import NumberOp
from .application import ALWAYS, WHOLE, Application
from .ops.operands import (
    SCOPE_OF,
    Effect,
    is_elementwise,
    resolve_condition,
    resolve_elementwise,
    resolve_mask,
    uses_companion,
)
from .ops.scope import ALL


def _with_list(body: str, exprs, companion: list[int] | None) -> str:
    """Append the line's private list when its text reads B."""
    if companion is not None and any(e is not None and uses_companion(e) for e in exprs):
        return f"{body} — this instruction's list B = {list(companion)}"
    return body


@dataclass(frozen=True)
class Instruction:
    """One data line: apply `op` with `operand`, landing on the list the
    way `application` says (every position, once, always — by default).

    hold_until_after: 1-based number of the instruction that must have
    executed first, or None to execute at its listed position.
    """

    op: NumberOp
    operand: object
    hold_until_after: int | None = None
    application: Application = WHOLE

    def render(self, number: int, companion: list[int] | None = None) -> str:
        how = self.application
        if how.extent is ALL:
            body = f"Replace every number with {self.op.render(self.operand)}"
        else:
            body = (
                f"For {how.extent.phrase}, replace it with "
                f"{self.op.wording(self.operand)} "
                f"({self.op.formula(self.operand)} where {how.extent.where})"
            )
        if how.times != 1:
            body = f"{body}, {how.times} times over"
        if how.gate is not ALWAYS:
            body = f"If {how.gate.phrase} ({how.gate.where}): {body}"
        body = _with_list(body, (self.operand, how.extent.where, how.gate.where), companion)
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


def render_question(instructions: list, companions: list[list[int]] | None = None) -> str:
    """The numbered question text. With companions, every line that reads
    B shows its own private list inline — the text is self-contained."""
    lines = []
    for i, ins in enumerate(instructions, start=1):
        companion = companions[i - 1] if companions is not None else None
        lines.append(ins.render(i, companion))
    return "\n".join(lines)


def _describe(definition) -> str:
    if definition is None:
        return "(cancelled)"
    op, operand, how, _owner = definition
    text = op.formula(operand)
    return text if how.extent is ALL else f"{text} where {how.extent.where}"


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
    # what each data instruction currently MEANS: (op, operand,
    # application, owner) — owner is the line whose private list B refers
    # to. Edits mutate this table, never the listing.
    definitions: dict[int, tuple[NumberOp, object, Application, int] | None] = {
        n: (ins.op, ins.operand, ins.application, n)
        for n, ins in enumerate(instructions, start=1)
        if isinstance(ins, Instruction)
    }
    # what actually ran: number -> (op, xs, mask), or None for no-ops/edits
    executed: dict[int, tuple[NumberOp, list[int], list[bool]] | None] = {}

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
                replacements[r] = definition[2].extent.where if definition else sp.false
            where = where.xreplace(replacements)
        raise ValueError("scope references never settle")

    def run_op(number: int, op: NumberOp, operand, how: Application, owner: int) -> None:
        nonlocal seq
        companion = list_of(owner)
        if not resolve_condition(how.gate.where, seq, effects, companion, original):
            run_noop(number, f"gate closed — {how.gate.phrase} does not hold")
            return
        per_element = is_elementwise(operand)
        before = seq
        for _ in range(how.times):  # operands and extent re-resolve every pass
            xs = resolve_elementwise(operand, seq, effects, companion, original)
            mask = resolve_mask(current_scope(how.extent.where), seq, effects, companion, original)
            if not any(mask):
                error = ValueError("scope selects no number")
                error.kind = "empty_scope"
                raise error
            seq = [op.apply(v, xv) if m else v for v, xv, m in zip(seq, xs, mask)]
        where = "" if how.extent is ALL else f" where {how.extent.where}"
        times = "" if how.times == 1 else f" x{how.times}"
        operation = (op.formula(operand) if per_element else op.formula(xs[0])) + where + times
        words = op.wording(operand) if per_element else op.wording(xs[0])
        changed = sum(1 for old, now in zip(before, seq) if old != now)
        effects[number] = Effect(changed, tuple(mask))
        executed[number] = (op, xs, mask)
        trace.append(Step(number, None if per_element else xs[0], xs if per_element else None,
                          operation, words, changed, list(seq)))

    def run_noop(number: int, why: str) -> None:
        effects[number] = nothing
        executed[number] = None
        trace.append(Step(number, None, None, "(no-op)", why, 0, list(seq)))

    def run_unwind(number: int, target: int) -> None:
        nonlocal seq
        record = executed.get(target)
        if record is None:
            run_noop(number, f"nothing to undo — instruction {target} did nothing")
            return
        op, xs, mask = record
        if op.inverse is None:
            raise ValueError(f"cannot undo {op.id} — it has no inverse")
        inverse = NUMBER_OPS[op.inverse]
        new = [inverse.apply(v, xv) if m else v for v, xv, m in zip(seq, xs, mask)]
        changed = sum(1 for old, now in zip(seq, new) if old != now)
        seq = new
        effects[number] = Effect(changed, tuple(mask))
        executed[number] = (inverse, xs, mask)
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
                    op, operand, how, owner = target_def
                    if verb.name == "amplify":
                        definitions[ins.target] = (op, 2 * sp.sympify(operand), how, owner)
                    elif verb.name == "flip":
                        if op.inverse is None:
                            raise ValueError(f"cannot flip {op.id} — it has no inverse")
                        definitions[ins.target] = (NUMBER_OPS[op.inverse], operand, how, owner)
                    elif verb.name == "rewrite":
                        # the new operand is written on the editor's line,
                        # so any B in it is the editor's list
                        definitions[ins.target] = (op, ins.operand, how, number)
                effects[number] = nothing
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
                    op, operand, how, owner = definition
                    if op.inverse is None:
                        raise ValueError(f"cannot negate {op.id} — it has no inverse")
                    run_op(number, NUMBER_OPS[op.inverse], operand, how, owner)
            else:  # undo klass
                run_unwind(number, ins.target)
        except ValueError as e:
            error = ValueError(f"instruction {number}: {e}")
            error.instruction = number
            error.kind = getattr(e, "kind", None)
            raise error from e

    return seq, trace

"""Instruction chains and their execution (pass 3 of the solver).

A chain mixes three kinds of lines:
- Instruction     — a MAP line: (op, operand, optional hold, application) —
  every touched value becomes op(value, x).
- MoveInstruction — a PERMUTE line: (move, optional hold, application) —
  values MOVE instead of changing (ops/moves.py). No op, no operand; its
  extent is locked to the whole list for now.
- MetaInstruction — a verb aimed at another instruction (mirror, negate,
  amplify, flip, rewrite, cancel, unwind). See meta/verbs.py.

A line's APPLICATION decides how it lands: its EXTENT (a Scope — which
positions; ALL by default; selecting nothing is an error, empty_scope —
a move whose permutation is the identity is dead the same way), its TIMES
(k passes, operands re-resolved and permutations composed per pass, one
trace event for the whole), and its GATE (a whole-list condition; closed =
a no-op event).

Every line may carry a private list B (its companion). B in an operand,
scope, or gate always means the list of the LINE THE TEXT IS WRITTEN ON —
a definition carries the owner of its B. A data line owns its own
definition; a rewrite installs an operand written on the editor's line, so
that definition's owner is the editor; mirror/negate execute j's
definition (application included) and so read j's list. Nothing can name
another line's list explicitly.

Execution keeps a DEFINITIONS table (MapDef | MoveDef | None-if-cancelled):
it starts as the listing and edit verbs mutate it, never the listing.
Apply-events always execute the CURRENT definition, so the trace records
what a line became, not just what it said. A cancelled line still executes
as an event (a no-op Step), so Changed[j] resolves to 0 and Touched[j, p]
to 0 everywhere.

Operands and scopes resolve at EXECUTION time; unwind is the one deliberate
exception — it replays the record: for a map line the exact x values on the
exact touched positions, for a move line the inverse of the executed
permutation (which is why even sort can be unwound).

The trace is event-based: Step for applications (including no-ops),
EditStep for definition changes.
"""

from dataclasses import dataclass

import sympy as sp

from .application import ALWAYS, WHOLE, Application
from .dag import schedule
from .meta.base import MetaInstruction
from .ops import NUMBER_OPS
from .ops.base import NumberOp
from .ops.moves import Move
from .ops.operands import (
    P,
    SCOPE_OF,
    Effect,
    is_elementwise,
    resolve,
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


def _decorate(body: str, how: Application, number: int, hold: int | None) -> str:
    """The application and hold wrappings shared by every data line."""
    if how.order != "snapshot":
        direction = "left to right" if how.order == "forward" else "right to left"
        body = (f"{body}, one number at a time moving {direction} "
                "(each number sees the numbers already updated before it)")
    if how.times != 1:
        body = f"{body}, {how.times} times over"
    if how.gate is not ALWAYS:
        body = f"If {how.gate.phrase} ({how.gate.where}): {body}"
    if hold is not None:
        return (
            f"{number}. Hold this instruction until instruction "
            f"{hold} has executed, then apply it: {body}"
        )
    return f"{number}. {body}"


@dataclass(frozen=True)
class Instruction:
    """One map line: apply `op` with `operand`, landing on the list the
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
        body = _with_list(body, (self.operand, how.extent.where, how.gate.where), companion)
        return _decorate(body, how, number, self.hold_until_after)


@dataclass(frozen=True)
class MoveInstruction:
    """One permute line: values move as `move` says (ops/moves.py)."""

    move: Move
    hold_until_after: int | None = None
    application: Application = WHOLE

    def render(self, number: int, companion: list[int] | None = None) -> str:
        body = f"{self.move.phrase} ({self.move.formula})"
        body = _with_list(body, (self.application.gate.where,), companion)
        return _decorate(body, self.application, number, self.hold_until_after)


@dataclass(frozen=True)
class Step:
    """One application event in the trace (including no-ops)."""

    instruction: int      # 1-based listing number
    x: int | None         # resolved operand value; None for per-element/move/no-op
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


@dataclass(frozen=True)
class MapDef:
    """What a map line currently means."""

    op: NumberOp
    operand: object
    how: Application
    owner: int  # the line whose private list a B in the text refers to


@dataclass(frozen=True)
class MoveDef:
    """What a move line currently means."""

    move: Move
    how: Application


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
    if isinstance(definition, MoveDef):
        return definition.move.formula
    text = definition.op.formula(definition.operand)
    if definition.how.extent is not ALL:
        text += f" where {definition.how.extent.where}"
    return text


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
    # what each data line currently MEANS. Edits mutate this table, never
    # the listing.
    definitions: dict[int, MapDef | MoveDef | None] = {}
    for n, ins in enumerate(instructions, start=1):
        if isinstance(ins, Instruction):
            definitions[n] = MapDef(ins.op, ins.operand, ins.application, n)
        elif isinstance(ins, MoveInstruction):
            definitions[n] = MoveDef(ins.move, ins.application)
    # what actually ran: map -> (op, [(xs, mask) per pass]); move ->
    # composed permutation. Unwind replays the WHOLE record, in reverse.
    executed: dict[int, tuple[NumberOp, list] | list[int] | None] = {}

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

    def dead(why: str) -> ValueError:
        error = ValueError(why)
        error.kind = "empty_scope"
        return error

    def gate_open(how: Application, companion) -> bool:
        return resolve_condition(how.gate.where, seq, effects, companion, original)

    def run_map(number: int, d: MapDef) -> None:
        nonlocal seq
        companion = list_of(d.owner)
        if not gate_open(d.how, companion):
            run_noop(number, f"gate closed — {d.how.gate.phrase} does not hold")
            return
        per_element = is_elementwise(d.operand) or d.how.order != "snapshot"
        before = seq
        where_expr = current_scope(d.how.extent.where)
        passes = []
        for _ in range(d.how.times):  # operands and extent re-resolve every pass
            if d.how.order == "snapshot":
                xs = resolve_elementwise(d.operand, seq, effects, companion, original)
                mask = resolve_mask(where_expr, seq, effects, companion, original)
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
                                             seq, effects, companion, original):
                        continue
                    xs[i] = resolve(sp.sympify(d.operand).subs(P, i),
                                    seq, effects, companion, original)
                    seq[i] = d.op.apply(seq[i], xs[i])
                    mask[i] = True
            if not any(mask):
                raise dead("scope selects no number")
            passes.append((xs, mask))
        where = "" if d.how.extent is ALL else f" where {d.how.extent.where}"
        times = "" if d.how.times == 1 else f" x{d.how.times}"
        order = "" if d.how.order == "snapshot" else f" {d.how.order}"
        operation = (d.op.formula(d.operand) if per_element else d.op.formula(xs[0])) + where + times + order
        words = d.op.wording(d.operand) if per_element else d.op.wording(xs[0])
        changed = sum(1 for old, now in zip(before, seq) if old != now)
        touched = tuple(any(m[i] for _, m in passes) for i in range(len(seq)))
        effects[number] = Effect(changed, touched)
        executed[number] = (d.op, passes)
        trace.append(Step(number, None if per_element else xs[0], xs if per_element else None,
                          operation, words, changed, list(seq)))

    def run_move(number: int, d: MoveDef) -> None:
        nonlocal seq
        companion = list_of(number)
        if not gate_open(d.how, companion):
            run_noop(number, f"gate closed — {d.how.gate.phrase} does not hold")
            return
        before = seq
        total = list(range(len(seq)))  # composed permutation across passes
        for _ in range(d.how.times):
            sigma = d.move.sigma(seq)
            seq = [seq[sigma[i]] for i in range(len(seq))]
            total = [total[sigma[i]] for i in range(len(seq))]
        if all(total[i] == i for i in range(len(seq))):
            raise dead("the move moves nothing")
        times = "" if d.how.times == 1 else f" x{d.how.times}"
        mask = [total[i] != i for i in range(len(seq))]
        changed = sum(1 for old, now in zip(before, seq) if old != now)
        effects[number] = Effect(changed, tuple(mask))
        executed[number] = total
        trace.append(Step(number, None, None, d.move.formula + times, d.move.phrase,
                          changed, list(seq)))

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
        before = seq
        if isinstance(record, list):  # a move: invert the executed permutation
            inverse = [0] * len(record)
            for i, s in enumerate(record):
                inverse[s] = i
            seq = [seq[inverse[i]] for i in range(len(seq))]
            xs, mask = None, [record[i] != i for i in range(len(seq))]
        else:  # a map: invert every pass, in reverse order
            op, passes = record
            if op.inverse is None:
                raise ValueError(f"cannot undo {op.id} — it has no inverse")
            inverse_op = NUMBER_OPS[op.inverse]
            for xs, mask in reversed(passes):
                seq = [inverse_op.apply(v, xv) if m else v for v, xv, m in zip(seq, xs, mask)]
            mask = [any(m[i] for _, m in passes) for i in range(len(seq))]
        changed = sum(1 for old, now in zip(before, seq) if old != now)
        effects[number] = Effect(changed, tuple(mask))
        trace.append(Step(number, None, xs, f"undo of instruction {target}",
                          f"undo what instruction {target} did", changed, list(seq)))

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

            verb = ins.verb
            if verb.klass == "edit":
                before = _describe(definitions.get(ins.target))
                target_def = definitions.get(ins.target)
                if verb.name == "cancel":
                    definitions[ins.target] = None
                elif isinstance(target_def, MapDef):
                    if verb.name == "amplify":
                        definitions[ins.target] = MapDef(
                            target_def.op, 2 * sp.sympify(target_def.operand),
                            target_def.how, target_def.owner)
                    elif verb.name == "flip":
                        if target_def.op.inverse is None:
                            raise ValueError(f"cannot flip {target_def.op.id} — it has no inverse")
                        definitions[ins.target] = MapDef(
                            NUMBER_OPS[target_def.op.inverse], target_def.operand,
                            target_def.how, target_def.owner)
                    elif verb.name == "rewrite":
                        # the new operand is written on the editor's line,
                        # so any B in it is the editor's list
                        definitions[ins.target] = MapDef(
                            target_def.op, ins.operand, target_def.how, number)
                elif isinstance(target_def, MoveDef) and verb.name == "flip":
                    flipped = target_def.move.inverse()
                    if flipped is None:
                        raise ValueError(f"cannot flip {target_def.move.name} — it has no inverse")
                    definitions[ins.target] = MoveDef(flipped, target_def.how)
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
                    run_definition(number, definition)
                elif isinstance(definition, MoveDef):  # negate a move
                    negated = definition.move.inverse()
                    if negated is None:
                        raise ValueError(f"cannot negate {definition.move.name} — it has no inverse")
                    run_move(number, MoveDef(negated, definition.how))
                else:  # negate a map
                    if definition.op.inverse is None:
                        raise ValueError(f"cannot negate {definition.op.id} — it has no inverse")
                    run_map(number, MapDef(NUMBER_OPS[definition.op.inverse],
                                           definition.operand, definition.how, definition.owner))
            else:  # undo klass
                run_unwind(number, ins.target)
        except ValueError as e:
            error = ValueError(f"instruction {number}: {e}")
            error.instruction = number
            error.kind = getattr(e, "kind", None)
            raise error from e

    return seq, trace

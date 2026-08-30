"""Invalidating broken chains — every error state, detected and named.

A chain is only usable if NO issue is found here. The question generator
must call validate() and re-roll anything that reports issues, so broken
states never reach a question.

Static issues (structure alone):
- trigger_out_of_range : hold/effect/meta ref points outside 1..k — e.g.
  the second-last instruction saying "after instruction i+4".
- self_reference       : an instruction waiting on, or targeting, itself.
- cycle                : circular holds (the infinite-loop state; nothing in
  the cycle can ever run), or definitions that read each other.
- unexecuted_reference : a line uses another line's RESULT (Changed[j],
  Touched[j, p], undo of j) but j has not run by its turn — only a hold
  moves a line in time, so the text asks for something that does not
  exist yet. A forward reference must carry its own hold.
- dead_edit            : "from now on, instruction j ..." when j has already
  run by the editor's turn — an edit of the past changes nothing.
- dead_hold            : a hold naming an EARLIER line. "Hold until k has
  executed, then apply it immediately after it" must be literally true;
  a hold always points forward.
- blocked              : depends, possibly transitively, on a broken
  instruction, so it can never run either.
- position_out_of_range: a fixed position outside the list (List/Start/
  Pos) or outside the line's private list (B). Own/offset/indirect
  positions are checked by the trial run (an offset off the end is
  undefined — no wrapping).
- companion_required   : a line's text reads B but the question gave that
  line no private list.
- bad_meta_target      : a meta verb aimed at another meta instruction
  (v1: verbs target data instructions only) — or a scope of "the same
  numbers as j" where j is a meta line (it has no scope).
- not_invertible       : negate/flip/unwind aimed at an op with no inverse
  (min, mod, floor-divide, ...).
- malformed_operand    : non-integer positions or instruction references,
  multi-index references, a rewrite without an operand, or an operand on a
  verb that takes none.
- reset                : a "replace with x" line over the WHOLE list whose x
  never reads the live list (a literal, Start, B, Pos, Changed) — it wipes
  every earlier line in one go. A partial replace (a scope) stays. A
  rewrite that plants such an operand into a whole-list replace line is
  the same breach, blamed on the editor. (decision 13)

Dynamic issues (need the actual list, found by trial run):
- undefined_operation  : an op hits an undefined point (division by zero,
  inexact unwind, ...) or an operand fails to resolve at execution time.
- empty_scope          : a line's scope selects no number at execution
  time — a dead line; never shipped. (A closed GATE is different: the
  line legitimately does nothing — a trap the model must compute.)
- collapse             : after some line the list holds fewer distinct
  values than the floor, max(2, ⌊min_distinct_fraction × length⌋) — a
  flat list makes every later line trivial; blamed on the line that
  flattened it (the first one). (decision 13)
- too_many_noops       : more lines leaving the list unchanged (a closed
  gate, a cancelled line, an undo of nothing, a read of a cancelled line,
  or a line that ran and changed nothing) than ⌈max_noop_fraction ×
  steps⌉ — cheap lines are rationed; blamed on the last such line.
  (decision 13; widened to "changed nothing" on 2026-09-03)
- locked_application   : an application combination that is locked with a
  reason (application.py locked_reason): an ordered move, a scoped swap,
  a form flag other than "map", or times < 1.
"""

from dataclasses import dataclass
from math import ceil

import sympy as sp

from .application import locked_reason
from .dag import consumes, schedule
from .instructions import NOOP, ExecutionError, Step, execute
from .lines import DataLine, Instruction, MoveInstruction
from .meta.base import MetaInstruction
from .ops.operands import B, L, P, POS, START, effect_refs, scope_refs, uses_live
from .ops.scope import ALL


@dataclass(frozen=True)
class Issue:
    kind: str
    instruction: int  # 1-based listing number the blame lands on
    message: str


@dataclass(frozen=True)
class Floors:
    """The acceptance floors a trial run is judged against. The numbers are
    generator config (GeneratorConfig); the validator only applies them."""

    min_distinct_fraction: float = 0.3  # distinct values EVERY state must keep
    max_noop_fraction: float = 0.15     # share of lines that may be no-op events

    def distinct(self, length: int) -> int:
        return max(2, int(self.min_distinct_fraction * length))

    def noops(self, steps: int) -> int:
        return ceil(self.max_noop_fraction * steps)


DEFAULT_FLOORS = Floors()


def _is_whole_replace(ins) -> bool:
    return isinstance(ins, Instruction) and ins.op.id == "x" and ins.application.extent is ALL


def _reset_issue(i: int, target: int, operand) -> Issue | None:
    """A whole-list "replace with x" whose x never reads the live list wipes
    every earlier line. Blamed on i: the line itself (target == i) or the
    editor that planted the operand into `target`."""
    if uses_live(operand):
        return None
    if target == i:
        what = f"instruction {i} replaces the whole list with something that never reads it"
    else:
        what = (f"instruction {i} plants an operand into instruction {target}, "
                "a whole-list replace, that never reads the list")
    return Issue("reset", i, f"{what} — every earlier line is wiped")


def _operand_issues(i, operand, length, companion_length):
    """companion_length: length of THIS line's private list, None if none."""
    issues = []
    for ref in sp.sympify(operand).atoms(sp.Indexed):
        if ref.base == L or ref.base == START or ref.base == POS:
            source, size = "the list", length
        elif ref.base == B:
            if companion_length is None:
                issues.append(
                    Issue(
                        "companion_required",
                        i,
                        f"instruction {i} reads its list B, but has no list",
                    )
                )
                continue
            source, size = "its list B", companion_length
        else:
            continue
        if len(ref.indices) != 1:
            issues.append(
                Issue(
                    "malformed_operand",
                    i,
                    f"reference {ref} takes exactly one position",
                )
            )
            continue
        pos = ref.indices[0]
        if pos.has(P) or pos.atoms(sp.Indexed):
            continue  # own/offset/indirect position; checked by the trial run
        if not pos.is_Integer:
            issues.append(
                Issue("malformed_operand", i, f"non-integer position {pos} in operand")
            )
        elif not 0 <= int(pos) < size:
            issues.append(
                Issue(
                    "position_out_of_range",
                    i,
                    f"instruction {i} reads position {pos} of {source}, "
                    f"but positions are 0..{size - 1}",
                )
            )
    return issues


def _meta_issues(i, ins: MetaInstruction, instructions):
    issues = []
    k = len(instructions)
    if ins.target == i:
        issues.append(Issue("self_reference", i, f"instruction {i} targets itself"))
    elif not 1 <= ins.target <= k:
        issues.append(
            Issue(
                "trigger_out_of_range",
                i,
                f"instruction {i} targets instruction {ins.target}, "
                f"but the chain is 1..{k}",
            )
        )
    elif isinstance(instructions[ins.target - 1], MetaInstruction):
        issues.append(
            Issue(
                "bad_meta_target",
                i,
                f"instruction {i} targets instruction {ins.target}, "
                "which is itself a meta instruction",
            )
        )
    else:
        target = instructions[ins.target - 1]
        if ins.verb.name in ("amplify", "rewrite") and not isinstance(target, Instruction):
            issues.append(
                Issue(
                    "bad_meta_target",
                    i,
                    f"instruction {i} wants to {ins.verb.name} instruction "
                    f"{ins.target}, which has no operand",
                )
            )
        elif ins.verb.name in ("negate", "flip") or (
            ins.verb.name == "unwind" and isinstance(target, Instruction)
        ):
            # unwind of a move always works — its permutation is recorded
            if isinstance(target, Instruction):
                invertible, what = target.op.inverse is not None, target.op.id
            else:
                invertible, what = target.move.inverse() is not None, target.move.name
            if not invertible:
                issues.append(
                    Issue(
                        "not_invertible",
                        i,
                        f"instruction {i} wants to {ins.verb.name} {what}, "
                        "which has no inverse",
                    )
                )
    if ins.verb.takes_operand and ins.operand is None:
        issues.append(
            Issue("malformed_operand", i, f"{ins.verb.name} needs an operand")
        )
    if not ins.verb.takes_operand and ins.operand is not None:
        issues.append(
            Issue("malformed_operand", i, f"{ins.verb.name} takes no operand")
        )
    return issues


def _cycles(graph: dict[int, set[int]]) -> set[int]:
    """Nodes on any cycle of a graph — depth-first, a back edge = a cycle."""
    state: dict[int, int] = {}  # absent=unvisited, 1=in progress, 2=done
    on_cycle: set[int] = set()

    def walk(node: int, path: list[int]) -> None:
        state[node] = 1
        path.append(node)
        for dep in graph.get(node, ()):
            if state.get(dep) == 1:
                on_cycle.update(path[path.index(dep):])
            elif dep not in state:
                walk(dep, path)
        path.pop()
        state[node] = 2

    for node in graph:
        if node not in state:
            walk(node, [])
    return on_cycle


def _static_issues(
    instructions: list, length: int, companions: list[list[int]] | None
) -> list[Issue]:
    k = len(instructions)
    issues: list[Issue] = []
    # only structurally sane references go here
    deps: dict[int, set[int]] = {i: set() for i in range(1, k + 1)}       # exec: holds
    reads: dict[int, set[int]] = {i: set() for i in range(1, k + 1)}      # def: must read first
    needs: dict[int, set[int]] = {}   # results a line consumes: must be behind it
    edits: dict[int, int] = {}        # editor -> target: must still be ahead of it
    planted: dict[int, set[int]] = {} # editor -> results its operand plants into the target
    broken: set[int] = set()

    for i, ins in enumerate(instructions, start=1):
        try:
            refs = consumes(ins)
        except ValueError as e:
            issues.append(Issue("malformed_operand", i, str(e)))
            broken.add(i)
            continue

        hold = ins.hold_until_after
        for j in sorted(refs | ({hold} if hold is not None else set())):
            if j == i:
                issues.append(Issue("self_reference", i, f"instruction {i} waits on or reads itself"))
                broken.add(i)
            elif not 1 <= j <= k:
                issues.append(
                    Issue(
                        "trigger_out_of_range",
                        i,
                        f"instruction {i} references instruction {j}, "
                        f"but the chain is 1..{k}",
                    )
                )
                broken.add(i)
            else:
                if j == hold:
                    if j < i:
                        issues.append(Issue("dead_hold", i,
                                            f"instruction {i} holds until instruction {j}, "
                                            "which is listed earlier — a hold names a later line"))
                        broken.add(i)
                    else:
                        deps[i].add(j)
                if j in refs:
                    needs.setdefault(i, set()).add(j)

        if isinstance(ins, MetaInstruction):
            meta_found = _meta_issues(i, ins, instructions)
            issues.extend(meta_found)
            if meta_found:
                broken.add(i)
            else:
                if ins.verb.klass == "edit":
                    edits[i] = ins.target
                    if ins.operand is not None:
                        try:
                            planted[i] = {j for j in effect_refs(ins.operand)}
                        except ValueError as e:
                            issues.append(Issue("malformed_operand", i, str(e)))
                            broken.add(i)
                        for j in sorted(planted.get(i, ())):
                            if not 1 <= j <= k:
                                issues.append(Issue(
                                    "trigger_out_of_range", i,
                                    f"instruction {i} plants a reference to instruction {j}, "
                                    f"but the chain is 1..{k}"))
                                broken.add(i)
                        if _is_whole_replace(instructions[ins.target - 1]):
                            reset = _reset_issue(i, ins.target, ins.operand)
                            if reset is not None:
                                issues.append(reset)
                                broken.add(i)
                if ins.verb.klass in ("read", "edit"):
                    reads[i].add(ins.target)

        companion_length = None
        if companions is not None and i - 1 < len(companions):
            companion_length = len(companions[i - 1])
        how = ins.application if isinstance(ins, DataLine) else None
        if how is not None:
            reason = locked_reason(
                how, ins.move.name if isinstance(ins, MoveInstruction) else None
            )
            if reason is not None:
                issues.append(Issue("locked_application", i, f"instruction {i}: {reason}"))
                broken.add(i)
            if scope_refs(how.gate.where):
                issues.append(Issue("malformed_operand", i,
                                    f"instruction {i}: a gate cannot be 'the same as' another line"))
                broken.add(i)
        exprs = [getattr(ins, "operand", None)] + ([how.extent.where, how.gate.where] if how else [])
        for expr in exprs:
            if expr is not None:
                found = _operand_issues(i, expr, length, companion_length)
                issues.extend(found)
                if found:
                    broken.add(i)
        if _is_whole_replace(ins):
            reset = _reset_issue(i, i, ins.operand)
            if reset is not None:
                issues.append(reset)
                broken.add(i)
        for j in (scope_refs(how.extent.where) if how else ()):
            if j == i:
                issues.append(Issue("self_reference", i, f"instruction {i} scopes on itself"))
            elif not 1 <= j <= k:
                issues.append(Issue("trigger_out_of_range", i,
                                    f"instruction {i} scopes on instruction {j}, but the chain is 1..{k}"))
            elif isinstance(instructions[j - 1], MetaInstruction):
                issues.append(Issue("bad_meta_target", i,
                                    f"instruction {i} scopes on instruction {j}, which has no scope"))
            else:
                reads[i].add(j)
                continue
            broken.add(i)

    # cycles — in the exec graph (circular holds) and in the def graph
    # (definitions that read each other: "same as" / mirror loops)
    in_cycle = _cycles(deps)
    for i in sorted(in_cycle):
        issues.append(Issue("cycle", i,
                            f"instruction {i} is in a dependency cycle with {sorted(deps[i] & in_cycle)}"))
    read_cycle = _cycles(reads)
    for i in sorted(read_cycle):
        issues.append(Issue("cycle", i,
                            f"instruction {i} is in a definition cycle with {sorted(reads[i] & read_cycle)}"))
    broken |= in_cycle | read_cycle

    # blocked: anything that transitively depends on a broken instruction
    def is_blocked(node: int, seen: set[int]) -> bool:
        seen.add(node)
        return any(
            dep in broken or (dep not in seen and is_blocked(dep, seen))
            for dep in deps.get(node, ())
        )

    for i in sorted(deps):
        if i not in broken and is_blocked(i, set()):
            issues.append(
                Issue("blocked", i, f"instruction {i} depends on an instruction that can never run")
            )

    # the timeline: only holds move a line, so the static schedule is final.
    # Everything a line CONSUMES must already be behind it there; an EDIT's
    # target must still be ahead. Blame lands on the line that asked.
    if not issues:
        position = {n: at for at, n in enumerate(schedule(instructions))}
        for i, js in sorted(needs.items()):
            for j in sorted(js):
                if position[j] > position[i]:
                    issues.append(Issue(
                        "unexecuted_reference", i,
                        f"instruction {i} uses the result of instruction {j}, "
                        "which has not run by then"))
        for i, j in sorted(edits.items()):
            if position[j] < position[i]:
                issues.append(Issue(
                    "dead_edit", i,
                    f"instruction {i} changes instruction {j}, which has already run by then"))
        # a planted operand (rewrite's x) is resolved when the TARGET runs:
        # its references are judged from the target's seat, blamed on the
        # editor who planted them
        for i, js in sorted(planted.items()):
            target = edits[i]
            for j in sorted(js):
                if position[j] > position[target]:
                    issues.append(Issue(
                        "unexecuted_reference", i,
                        f"instruction {i} plants the result of instruction {j} into "
                        f"instruction {target}, but {j} has not run by {target}'s turn"))

    return issues


def validate(
    instructions: list,
    start: list[int],
    companions: list[list[int]] | None = None,
    floors: Floors = DEFAULT_FLOORS,
) -> list[Issue]:
    """All issues in a chain, static and dynamic. Empty list == valid.

    companions[k-1] is instruction k's private list B (or None for none).
    floors: the acceptance floors the trial run is judged against.
    """
    issues = _static_issues(instructions, len(start), companions)
    if issues:
        return issues  # structure is broken; a trial run would be meaningless

    try:
        _, trace = execute(instructions, start, companions)
    except ExecutionError as e:
        return [Issue(e.kind or "undefined_operation", e.instruction, str(e))]

    # the trial run passed; now the floors, on every state it produced
    steps = [event for event in trace if isinstance(event, Step)]
    floor = floors.distinct(len(start))
    for step in steps:
        distinct = len(set(step.seq))
        if distinct < floor:
            issues.append(Issue(
                "collapse", step.instruction,
                f"after instruction {step.instruction} the list holds {distinct} distinct "
                f"values; every state must keep at least {floor}"))
            break  # the first flattening line is the one to blame
    # a no-op is any line that left the list unchanged: the explicit no-op
    # events AND a line that ran but changed nothing (ruling 2026-09-03)
    noops = [step for step in steps if step.changed == 0]
    allowed = floors.noops(len(instructions))
    if len(noops) > allowed:
        last = noops[-1].instruction
        issues.append(Issue(
            "too_many_noops", last,
            f"{len(noops)} lines leave the list unchanged, at most {allowed} may — "
            f"instruction {last} is the last of them"))
    return issues

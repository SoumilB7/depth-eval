"""Invalidating broken chains — every error state, detected and named.

A chain is only usable if NO issue is found here. The question generator
must call validate() and re-roll anything that reports issues, so broken
states never reach a question.

Static issues (structure alone):
- trigger_out_of_range : hold/effect/meta ref points outside 1..k — e.g.
  the second-last instruction saying "after instruction i+4".
- self_reference       : an instruction waiting on, or targeting, itself.
- cycle                : circular dependencies (mutual waits, or edits that
  circle — the infinite-loop state; nothing in the cycle can ever run).
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

Dynamic issues (need the actual list, found by trial run):
- undefined_operation  : an op hits an undefined point (division by zero,
  inexact unwind, ...) or an operand fails to resolve at execution time.
- empty_scope          : a line's scope selects no number at execution
  time — a dead line; never shipped. (A closed GATE is different: the
  line legitimately does nothing — a trap the model must compute.)
- locked_application   : an application axis that is declared but not yet
  enabled (FORM=permute, ORDER=forward|backward), or times < 1.
"""

from dataclasses import dataclass

import sympy as sp

from .application import ENABLED
from .dag import own_triggers
from .instructions import Instruction, MoveInstruction, execute
from .meta.base import MetaInstruction
from .ops.operands import B, L, P, POS, START, scope_refs


@dataclass(frozen=True)
class Issue:
    kind: str
    instruction: int  # 1-based listing number the blame lands on
    message: str


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


def _static_issues(
    instructions: list, length: int, companions: list[list[int]] | None
) -> list[Issue]:
    k = len(instructions)
    issues: list[Issue] = []
    # only structurally sane deps go here; pre-initialized because an edit
    # verb adds an edge onto its TARGET, which may not be visited yet
    deps: dict[int, set[int]] = {i: set() for i in range(1, k + 1)}
    broken: set[int] = set()

    for i, ins in enumerate(instructions, start=1):
        try:
            refs = own_triggers(ins)
        except ValueError as e:
            issues.append(Issue("malformed_operand", i, str(e)))
            broken.add(i)
            continue

        for j in refs:
            if j == i:
                issues.append(Issue("self_reference", i, f"instruction {i} waits on itself"))
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
                deps[i].add(j)

        if isinstance(ins, MetaInstruction):
            meta_found = _meta_issues(i, ins, instructions)
            issues.extend(meta_found)
            if meta_found:
                broken.add(i)
            elif ins.verb.klass == "edit":
                deps[ins.target].add(i)  # target waits for its editor

        companion_length = None
        if companions is not None and i - 1 < len(companions):
            companion_length = len(companions[i - 1])
        how = getattr(ins, "application", None)
        if how is not None:
            for axis, allowed in ENABLED.items():
                if getattr(how, axis) not in allowed:
                    issues.append(Issue("locked_application", i,
                                        f"instruction {i}: {axis}={getattr(how, axis)!r} is not enabled yet"))
                    broken.add(i)
            if how.times < 1:
                issues.append(Issue("locked_application", i, f"instruction {i}: times must be >= 1"))
                broken.add(i)
            if isinstance(ins, MoveInstruction) and how.extent.kind != "all":
                issues.append(Issue("locked_application", i,
                                    f"instruction {i}: a scoped move is not enabled yet"))
                broken.add(i)
        exprs = (getattr(ins, "operand", None),) + ((how.extent.where, how.gate.where) if how else ())
        for expr in exprs:
            if expr is not None:
                found = _operand_issues(i, expr, length, companion_length)
                issues.extend(found)
                if found:
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
                continue
            broken.add(i)

    # cycles: walk depth-first over sane deps; a back edge = a cycle
    state: dict[int, int] = {}  # 0/absent=unvisited, 1=in progress, 2=done
    in_cycle: set[int] = set()

    def walk(node: int, path: list[int]) -> None:
        state[node] = 1
        path.append(node)
        for dep in deps.get(node, ()):
            if state.get(dep) == 1:
                loop = path[path.index(dep):]
                in_cycle.update(loop)
            elif state.get(dep, 0) == 0:
                walk(dep, path)
        path.pop()
        state[node] = 2

    for i in deps:
        if state.get(i, 0) == 0:
            walk(i, [])
    for i in sorted(in_cycle):
        cycle_deps = sorted(deps[i] & in_cycle)
        issues.append(
            Issue("cycle", i, f"instruction {i} is in a dependency cycle with {cycle_deps}")
        )
    broken |= in_cycle

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

    return issues


def validate(
    instructions: list,
    start: list[int],
    companions: list[list[int]] | None = None,
) -> list[Issue]:
    """All issues in a chain, static and dynamic. Empty list == valid.

    companions[k-1] is instruction k's private list B (or None for none).
    """
    issues = _static_issues(instructions, len(start), companions)
    if issues:
        return issues  # structure is broken; a trial run would be meaningless

    try:
        execute(instructions, start, companions)
    except (ValueError, ZeroDivisionError) as e:
        number = getattr(e, "instruction", 0)
        issues.append(Issue(getattr(e, "kind", None) or "undefined_operation", number, str(e)))
    return issues

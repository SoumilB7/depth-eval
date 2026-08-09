"""Invalidating broken chains — every error state, detected and named.

A chain is only usable if NO issue is found here. The question generator
must call validate() and re-roll anything that reports issues, so broken
states never reach a question.

Static issues (structure alone):
- trigger_out_of_range : hold/effect ref points outside 1..k — e.g. the
  second-last instruction saying "after instruction i+4".
- self_reference       : an instruction waiting on itself.
- cycle                : circular dependencies (mutual waits — the
  infinite-loop state; nothing in the cycle can ever run).
- blocked              : depends, possibly transitively, on a broken
  instruction, so it can never run either.
- position_out_of_range: At(p) outside the list, or B[i] outside the
  companion.
- companion_required   : operand references B but the question has no
  companion list.
- malformed_operand    : non-integer positions or instruction references
  (indices built from the position symbol P are fine — they resolve
  per element).

Dynamic issues (need the actual list, found by trial run):
- undefined_operation  : an op hits an undefined point (division by zero,
  negative exponent) or an operand fails to resolve at execution time.
"""

from dataclasses import dataclass

import sympy as sp

from .dag import triggers
from .instructions import Instruction, execute
from .ops.operands import B, L, P


@dataclass(frozen=True)
class Issue:
    kind: str
    instruction: int  # 1-based listing number the blame lands on
    message: str


def _static_issues(
    instructions: list[Instruction], length: int, companion_length: int | None
) -> list[Issue]:
    k = len(instructions)
    issues: list[Issue] = []
    deps: dict[int, set[int]] = {}   # only structurally sane deps go here
    broken: set[int] = set()

    for i, ins in enumerate(instructions, start=1):
        try:
            refs = triggers(ins)
        except ValueError as e:
            issues.append(Issue("malformed_operand", i, str(e)))
            broken.add(i)
            continue

        deps[i] = set()
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

        for ref in sp.sympify(ins.operand).atoms(sp.Indexed):
            if ref.base == L:
                target, size = "the list", length
            elif ref.base == B:
                if companion_length is None:
                    issues.append(
                        Issue(
                            "companion_required",
                            i,
                            f"instruction {i} references list B, "
                            "but the question has no companion list",
                        )
                    )
                    broken.add(i)
                    continue
                target, size = "list B", companion_length
            else:
                continue
            p = ref.indices[0]
            if p.has(P):
                continue  # position-dependent index; checked by the trial run
            if not p.is_Integer:
                issues.append(
                    Issue("malformed_operand", i, f"non-integer position {p} in operand")
                )
                broken.add(i)
            elif not 0 <= int(p) < size:
                issues.append(
                    Issue(
                        "position_out_of_range",
                        i,
                        f"instruction {i} reads position {p}, "
                        f"but {target} is 0..{size - 1}",
                    )
                )
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
    instructions: list[Instruction],
    start: list[int],
    companion: list[int] | None = None,
) -> list[Issue]:
    """All issues in a chain, static and dynamic. Empty list == valid."""
    issues = _static_issues(
        instructions, len(start), None if companion is None else len(companion)
    )
    if issues:
        return issues  # structure is broken; a trial run would be meaningless

    try:
        execute(instructions, start, companion)
    except (ValueError, ZeroDivisionError) as e:
        number = getattr(e, "instruction", 0)
        issues.append(Issue("undefined_operation", number, str(e)))
    return issues

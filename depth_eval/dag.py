"""Passes 1–2 of the solver: the dependency DAG and its schedule.

Nodes are the listed instructions (1-based). Two edge kinds exist:

- "exec"  j => i : i cannot RUN until j has run. Sources: explicit holds,
  effect references (Changed[j] / Touched[j, p] in an operand or a scope),
  undo verbs (unwind needs the target's execution record), and EDIT verbs
  — reversed: the edit creates exec editor => target, so the TARGET parks
  until its editor has run (its definition isn't final before that).
- "def"   j -> i : i cannot be INTERPRETED without j's text — read verbs
  (mirror/negate), edit verbs, and a scope of "the same numbers as j"
  (ScopeOf[j]) create these. Def edges never reorder anything.

Scheduling walks the listing in order; an instruction whose exec
dependencies aren't all satisfied parks and is released immediately after
the last of its triggers runs (same-trigger releases keep listed order;
releases cascade). The schedule is STATIC — it depends only on the
instructions, never on list data — so it is computed here once and the
executor just replays it.

Unschedulable chains (self-reference, circular dependencies, triggers out
of range) raise; the question generator must never emit them.
"""

from dataclasses import dataclass

from .meta.base import MetaInstruction
from .ops.operands import effect_refs, scope_refs


@dataclass(frozen=True)
class Edge:
    kind: str  # "exec" or "def"
    src: int   # must run first (exec) / must be read (def)
    dst: int


def own_triggers(instruction) -> set[int]:
    """Exec dependencies an instruction declares for ITSELF."""
    refs: set[int] = set()
    scope = getattr(instruction, "scope", None)
    for expr in (getattr(instruction, "operand", None), scope.where if scope else None):
        if expr is not None:
            refs |= effect_refs(expr)
    if instruction.hold_until_after is not None:
        refs.add(instruction.hold_until_after)
    if isinstance(instruction, MetaInstruction) and instruction.verb.klass == "undo":
        refs.add(instruction.target)
    return refs


def chain_triggers(instructions) -> dict[int, set[int]]:
    """All exec dependencies, including edit edges imposed ON targets."""
    triggers = {n: own_triggers(ins) for n, ins in enumerate(instructions, start=1)}
    for n, ins in enumerate(instructions, start=1):
        if isinstance(ins, MetaInstruction) and ins.verb.klass == "edit":
            if 1 <= ins.target <= len(instructions) and ins.target != n:
                triggers[ins.target].add(n)  # target waits for its editor
    return triggers


def build_edges(instructions) -> list[Edge]:
    edges = [
        Edge("exec", src, dst)
        for dst, refs in chain_triggers(instructions).items()
        for src in sorted(refs)
    ]
    for n, ins in enumerate(instructions, start=1):
        if isinstance(ins, MetaInstruction) and ins.verb.klass in ("read", "edit"):
            edges.append(Edge("def", ins.target, n))
        scope = getattr(ins, "scope", None)
        if scope is not None:
            edges += [Edge("def", j, n) for j in sorted(scope_refs(scope.where))]
    return edges


def schedule(instructions) -> list[int]:
    """Execution order for a chain (pass 2). Raises if unschedulable."""
    triggers = chain_triggers(instructions)
    executed: set[int] = set()
    parked: dict[int, list[int]] = {}
    order: list[int] = []

    def run(number: int) -> None:
        executed.add(number)
        order.append(number)
        for waiting in parked.pop(number, []):
            attempt(waiting)

    def attempt(number: int) -> None:
        gaps = triggers[number] - executed
        if gaps:
            parked.setdefault(min(gaps), []).append(number)
        else:
            run(number)

    for number in range(1, len(instructions) + 1):
        attempt(number)

    if parked:
        stuck = sorted(number for waiting in parked.values() for number in waiting)
        raise ValueError(
            f"instructions {stuck} can never execute "
            "(self-reference, circular dependencies, or trigger out of range)"
        )
    return order

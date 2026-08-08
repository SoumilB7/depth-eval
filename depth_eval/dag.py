"""Passes 1–2 of the solver: the dependency DAG and its schedule.

Nodes are the listed instructions (1-based). Two edge kinds exist:

- "exec"  j => i : i cannot RUN until j has run. Sources: explicit holds
  and effect references (Changed(j) in i's operand — auto-hold, no explicit
  hold clause needed, past or future).
- "def"   j -> i : i cannot be INTERPRETED without j's text. Reserved for
  the meta-op vocabulary (not populated yet).

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

from .ops.operands import effect_refs


@dataclass(frozen=True)
class Edge:
    kind: str  # "exec" or "def"
    src: int   # must run first (exec) / must be read (def)
    dst: int


def triggers(instruction) -> set[int]:
    """Instruction numbers that must have executed before this one runs."""
    refs = set(effect_refs(instruction.operand))
    if instruction.hold_until_after is not None:
        refs.add(instruction.hold_until_after)
    return refs


def build_edges(instructions) -> list[Edge]:
    return [
        Edge("exec", src, dst)
        for dst, ins in enumerate(instructions, start=1)
        for src in sorted(triggers(ins))
    ]


def schedule(instructions) -> list[int]:
    """Execution order for a chain (pass 2). Raises if unschedulable."""
    executed: set[int] = set()
    parked: dict[int, list[int]] = {}
    order: list[int] = []

    def missing(number: int) -> set[int]:
        return triggers(instructions[number - 1]) - executed

    def run(number: int) -> None:
        executed.add(number)
        order.append(number)
        for waiting in parked.pop(number, []):
            attempt(waiting)

    def attempt(number: int) -> None:
        gaps = missing(number)
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

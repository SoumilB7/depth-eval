"""Passes 1–2 of the solver: the dependency DAG and its schedule.

Nodes are the listed instructions (1-based). Two edge kinds exist:

- "exec"  j => i : i cannot RUN until j has run. ONE source: an explicit
  hold ("hold this instruction until instruction j has executed"). Nothing
  else moves a line in time. A line that CONSUMES another's result
  (Changed[j] / Touched[j, p] in an operand, scope or gate; undo of j)
  does not force j first — j must already be behind it in the schedule,
  or the question is invalid (validation.py: unexecuted_reference). An
  edit ("from now on, instruction j ...") never parks its target — j must
  still be ahead (dead_edit otherwise). The timeline a model has to follow
  is therefore exactly what it reads: numbered order plus the holds.
- "def"   j -> i : i cannot be INTERPRETED without j's text — read verbs
  (mirror/negate), edit verbs, and a scope of "the same selection as j"
  (ScopeOf[j]) create these. Def edges never reorder anything.

Scheduling walks the listing in order; an instruction whose hold target
has not run parks and is released immediately after it runs (same-trigger
releases keep listed order; releases cascade). The schedule is STATIC —
it depends only on the instructions, never on list data — so it is
computed here once and the executor just replays it.

Unschedulable chains (self-hold, circular holds, holds out of range)
raise; the question generator must never emit them.
"""

from dataclasses import dataclass

from .lines import DataLine
from .meta.base import MetaInstruction
from .ops.operands import effect_refs, scope_refs


@dataclass(frozen=True)
class Edge:
    kind: str  # "exec" or "def"
    src: int   # must run first (exec) / must be read (def)
    dst: int


def consumes(instruction) -> set[int]:
    """Lines whose RESULT this instruction uses. They must have run before
    it — a constraint the validator checks against the schedule, not an
    edge that would move anything."""
    refs: set[int] = set()
    exprs = [getattr(instruction, "operand", None)]
    if isinstance(instruction, MetaInstruction) and instruction.verb.klass == "edit":
        exprs = []  # a rewrite's operand is PLANTED into the target and
        #             resolved at the TARGET's turn — the validator judges
        #             its references from that seat, not the editor's
    if isinstance(instruction, DataLine):
        exprs += [instruction.application.extent.where, instruction.application.gate.where]
    for expr in exprs:
        if expr is not None:
            refs |= effect_refs(expr)
    if isinstance(instruction, MetaInstruction) and instruction.verb.klass == "undo":
        refs.add(instruction.target)
    return refs


def chain_triggers(instructions) -> dict[int, set[int]]:
    """Exec dependencies: each line's hold target, if it has one."""
    return {
        n: {ins.hold_until_after} if ins.hold_until_after is not None else set()
        for n, ins in enumerate(instructions, start=1)
    }


def build_edges(instructions) -> list[Edge]:
    edges = [
        Edge("exec", src, dst)
        for dst, refs in chain_triggers(instructions).items()
        for src in sorted(refs)
    ]
    for n, ins in enumerate(instructions, start=1):
        if isinstance(ins, MetaInstruction) and ins.verb.klass in ("read", "edit"):
            edges.append(Edge("def", ins.target, n))
        if isinstance(ins, DataLine):
            edges += [Edge("def", j, n) for j in sorted(scope_refs(ins.application.extent.where))]
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
            "(self-hold, circular holds, or a hold out of range)"
        )
    return order

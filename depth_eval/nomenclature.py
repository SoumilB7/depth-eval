"""The forced nomenclature: every instruction is DIRECT or RELATIVE.

RELATIVE = coupled to another instruction — it takes another instruction's
output as its input, or it changes another instruction's output.
DIRECT   = everything else. Reading the data (the live list, its origin,
companion rows, positions) is NOT relative: data is not an instruction's
output. List[0] is direct.

    DIRECT
      literal      n + 7
      live         List[i]            current list, read at execution
      origin       Start[i], Start[p]
      companion    B[k, i], B[k, p]
      positional   p
      composite    any mix of the above
    RELATIVE
      consumes — uses another instruction's output as input
        effect       Changed[j]
        execution    unwind j          (j's recorded execution)
        definition   mirror j, negate j (j's current meaning)
      affects — changes another instruction's output
        alter        amplify j, flip j, rewrite j
        erase        cancel j

A hold is a TAG ("held"), not a category: it changes when a line runs,
never what it consumes or affects.

Intent: one forced vocabulary so every question, config, and result speaks
the same names — and so "relative depth" (instruction coupling) can be
measured separately from data-reading load.
"""

from collections import Counter
from dataclasses import dataclass

import sympy as sp

from .instructions import Instruction
from .meta.base import MetaInstruction
from .ops.operands import B, L, P, START, _CHANGED

RELATIVE_KINDS = {
    "mirror": ("consumes", "definition"),
    "negate": ("consumes", "definition"),
    "unwind": ("consumes", "execution"),
    "amplify": ("affects", "alter"),
    "flip": ("affects", "alter"),
    "rewrite": ("affects", "alter"),
    "cancel": ("affects", "erase"),
}


@dataclass(frozen=True)
class Label:
    category: str          # "direct" | "relative"
    group: str | None      # relative only: "consumes" | "affects"
    kind: str              # leaf name (literal, live, ..., effect, alter, ...)
    tags: tuple[str, ...]  # ("held",) when hold_until_after is set

    def __str__(self) -> str:
        path = f"{self.category}.{self.kind}" if self.group is None \
            else f"{self.category}.{self.group}.{self.kind}"
        return path + "".join(f"+{t}" for t in self.tags)


def _data_kind(operand) -> tuple[str, str | None, str]:
    expr = sp.sympify(operand)
    refs = expr.atoms(sp.Indexed)
    if any(r.base == _CHANGED for r in refs):
        return "relative", "consumes", "effect"
    sources = set()
    if any(r.base == L for r in refs):
        sources.add("live")
    if any(r.base == START for r in refs):
        sources.add("origin")
    if any(r.base == B for r in refs):
        sources.add("companion")
    if expr.has(P):
        sources.add("positional")
    if not sources:
        return "direct", None, "literal"
    if len(sources) == 1:
        return "direct", None, sources.pop()
    return "direct", None, "composite"


def classify(instruction) -> Label:
    tags = ("held",) if instruction.hold_until_after is not None else ()
    if isinstance(instruction, Instruction):
        category, group, kind = _data_kind(instruction.operand)
        return Label(category, group, kind, tags)
    if isinstance(instruction, MetaInstruction):
        group, kind = RELATIVE_KINDS[instruction.verb.name]
        return Label("relative", group, kind, tags)
    raise TypeError(f"unknown instruction kind: {type(instruction).__name__}")


def mix(instructions) -> dict[str, int]:
    """Realized nomenclature counts for a chain, e.g. {'direct.live': 3, ...}."""
    return dict(Counter(str(classify(ins)) for ins in instructions))


def split(instructions) -> dict[str, int]:
    """Just the top-level split: {'direct': n, 'relative': m}."""
    return dict(Counter(classify(ins).category for ins in instructions))

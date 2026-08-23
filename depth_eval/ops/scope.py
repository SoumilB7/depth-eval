"""Scope — which numbers a line touches.

A scope is one SymPy boolean over p (and any applier), evaluated per
position in the same snapshot-before-the-pass way operands are. A line
applies its op only where the scope is true. Every line has one; ALL is
what every line had before scopes existed.

    kind      where (formula)                       text
    all       true                                  every number
    stride    Mod(p - phase, step) == 0             every 3rd number from position 2
              Mod((L-1-p) - phase, step) == 0       ... counting from the end
    span      a <= p <= b (inclusive)               the numbers at positions 2 to 5
    value     Mod(List[p], 2) == 0, List[p] > x     every even number / greater than x
    touched   Touched[j, p] == 1 | == 0             every number instruction j applied to
    same      ScopeOf[j]                            the same numbers as instruction j

Scopes compose with And/Or/Not for free (expressible, not drawn).
touched/same couple the line to instruction j — relative ground: touched
needs j to have run (exec edge, like Changed[j]); same reads j's current
definition (def edge, like mirror). A scope selecting NO number makes the
question invalid (empty_scope).
"""

from dataclasses import dataclass

import sympy as sp

from .operands import _CHANGED, L, P, SCOPE_OF, TOUCHED
from .operands import phrase as operand_phrase

SCOPE_KINDS = ("all", "stride", "span", "value", "touched", "same")
GATE_KINDS = ("always", "value", "effect")


@dataclass(frozen=True)
class Scope:
    kind: str      # one of SCOPE_KINDS
    where: object  # SymPy boolean over p
    phrase: str    # "every 3rd number from position 2"


ALL = Scope("all", sp.true, "every number")


def _ordinal(k: int) -> str:
    suffix = "th" if 10 <= k % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(k % 10, "th")
    return f"{k}{suffix}"


def stride(step: int, phase: int = 0, length: int | None = None, from_end: bool = False) -> Scope:
    """Every `step`-th position, starting `phase` in from the front — or
    from the end (length is baked in so the formula is concrete)."""
    if from_end:
        position, tail = length - 1 - P, "counting from the end"
        if phase:
            tail += f", starting {phase} from the last"
    else:
        position, tail = P, f"from position {phase}"
    where = sp.Eq(sp.Mod(position - phase, step), 0)
    if length is not None:  # spell the positions out — no counting ambiguity
        chosen = [i for i in range(length) if where.subs(P, i)]
        tail += f" (positions {', '.join(map(str, chosen))})"
    return Scope("stride", where, f"every {_ordinal(step)} number {tail}")


def span(a: int, b: int) -> Scope:
    return Scope("span", sp.And(P >= a, P <= b), f"the numbers at positions {a} to {b}")


def even() -> Scope:
    return Scope("value", sp.Eq(sp.Mod(L[P], 2), 0), "every even number")


def odd() -> Scope:
    return Scope("value", sp.Eq(sp.Mod(L[P], 2), 1), "every odd number")


def above(x) -> Scope:
    return Scope("value", sp.Gt(L[P], sp.sympify(x)),
                 f"every number greater than {operand_phrase(x)}")


def touched(j: int) -> Scope:
    return Scope("touched", sp.Eq(TOUCHED[j, P], 1),
                 f"every number at a position instruction {j} applied to")


def untouched(j: int) -> Scope:
    return Scope("touched", sp.Eq(TOUCHED[j, P], 0),
                 f"every number at a position instruction {j} did not apply to")


def same_as(j: int) -> Scope:
    return Scope("same", SCOPE_OF[j],
                 f"the same selection as instruction {j} (its current rule, judged on the list now)")


# --- gates: whole-list conditions (no p) — the GATE axis of an Application ---

def even_at(i: int) -> Scope:
    return Scope("value", sp.Eq(sp.Mod(L[i], 2), 0), f"the number at position {i} is even")


def odd_at(i: int) -> Scope:
    return Scope("value", sp.Eq(sp.Mod(L[i], 2), 1), f"the number at position {i} is odd")


def bigger_at(i: int, x) -> Scope:
    return Scope("value", sp.Gt(L[i], sp.sympify(x)),
                 f"the number at position {i} is greater than {operand_phrase(x)}")


def changed_more(j: int, c: int) -> Scope:
    return Scope("effect", sp.Gt(_CHANGED[j], c),
                 f"instruction {j} changed more than {c} numbers")

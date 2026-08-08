"""Operands — what x resolves from.

The operand of an operation is itself a SymPy expression:
- a literal:            Integer(4)
- a list reference:     At(4)  — the number at 1-indexed position 4
- any composition:      At(4) + 1, Abs(At(2) - At(9)), ...

`resolve` is the main operator here: it collapses an operand expression to a
concrete integer against the CURRENT list (the state before the instruction
executes), which is then pawned into a NumberOp as x. Resolution happens
ONCE per instruction — not per element while the list mutates.

Positions are 1-indexed; a position outside [1, len(list)] makes the operand
unresolvable (the question generator must avoid emitting it).
"""

import sympy as sp


class At(sp.Function):
    """The value at a 1-indexed position of the current list.

    Stays symbolic until resolved against an actual list — resolution needs
    the list, so it never self-evaluates.
    """


def resolve(operand, seq: list[int]) -> int:
    """Collapse an operand expression to a concrete integer against seq."""
    expr = sp.sympify(operand)

    def lookup(p):
        if not p.is_Integer:
            raise ValueError(f"non-integer position in {expr}")
        i = int(p)
        if not 1 <= i <= len(seq):
            raise ValueError(f"position {i} out of range 1..{len(seq)}")
        return sp.Integer(seq[i - 1])

    result = expr.replace(At, lookup)
    if result.is_Integer is not True:
        raise ValueError(f"operand {expr} did not resolve to an integer")
    return int(result)


def resolvable(operand, seq: list[int]) -> bool:
    try:
        resolve(operand, seq)
        return True
    except (ValueError, ZeroDivisionError):
        return False


def phrase(operand) -> str:
    """English for an operand: 4 -> '4', At(4) -> 'the number at position 4'.

    Composite operands fall back to their formula form — structure to
    string, one way, as always.
    """
    expr = sp.sympify(operand)
    if isinstance(expr, At):
        return f"the number at position {expr.args[0]}"
    return str(expr)

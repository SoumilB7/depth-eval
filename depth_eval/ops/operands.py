"""Operands — what x resolves from.

The operand of an operation is itself a SymPy expression:
- a literal:            Integer(4)
- a list reference:     At(4) == L[4] — the value at 0-indexed position 4
- any composition:      At(4) + 1, Abs(At(2) - At(9)), ...

The list is the SymPy IndexedBase `L`; At(p) is L[p], SymPy's native
indexing object, so references compose into every expression (Max, Mod,
floor, ...) and print as L[4].

`resolve` is the main operator here: it collapses an operand expression to a
concrete integer against the CURRENT list (the state at the moment the
instruction executes), which is then pawned into a NumberOp as x.
Resolution happens ONCE per instruction — not per element while the list
mutates.

Positions are 0-indexed; a position outside [0, len(list) - 1] makes the
operand unresolvable (the question generator must avoid emitting it).
"""

import sympy as sp

L = sp.IndexedBase("L", integer=True)


def At(position: int) -> sp.Indexed:
    """The value at a 0-indexed position of the current list."""
    return L[position]


_CHANGED = sp.IndexedBase("Changed", integer=True)


def Changed(j: int) -> sp.Indexed:
    """The count of positions whose value changed when instruction j last
    executed (j is a 1-based instruction listing number). Prints Changed[j].

    An EFFECT reference: resolving it requires instruction j to have already
    executed, so it creates an exec dependency — the executor auto-holds the
    referencing instruction until j has run, past or future. With repeats,
    "last executed" means the most recent execution. Like At/L[p], it is
    native SymPy indexing, so it composes into every op (Max/Min included).
    """
    return _CHANGED[j]


def _is_effect_ref(e) -> bool:
    return isinstance(e, sp.Indexed) and e.base == _CHANGED


def effect_refs(operand) -> set[int]:
    """Instruction numbers whose effect the operand references."""
    refs = set()
    for e in sp.sympify(operand).atoms(sp.Indexed):
        if not _is_effect_ref(e):
            continue
        j = e.indices[0]
        if not j.is_Integer:
            raise ValueError(f"non-integer instruction reference in {operand}")
        refs.add(int(j))
    return refs


def resolve(operand, seq: list[int], effects: dict[int, int] | None = None) -> int:
    """Collapse an operand expression to a concrete integer.

    seq is the CURRENT list; effects maps instruction number -> change count
    of its latest execution (for Changed references).
    """
    expr = sp.sympify(operand)

    def lookup(ref: sp.Indexed) -> sp.Integer:
        p = ref.indices[0]
        if not p.is_Integer:
            raise ValueError(f"non-integer position in {expr}")
        i = int(p)
        if not 0 <= i < len(seq):
            raise ValueError(f"position {i} out of range 0..{len(seq) - 1}")
        return sp.Integer(seq[i])

    def lookup_effect(ref: sp.Indexed) -> sp.Integer:
        j = int(ref.indices[0])
        if effects is None or j not in effects:
            raise ValueError(f"instruction {j} has not executed — {expr} unresolvable")
        return sp.Integer(effects[j])

    result = expr.replace(lambda e: isinstance(e, sp.Indexed) and e.base == L, lookup)
    result = result.replace(_is_effect_ref, lookup_effect)
    if result.is_Integer is not True:
        raise ValueError(f"operand {expr} did not resolve to an integer")
    return int(result)


def resolvable(operand, seq: list[int], effects: dict[int, int] | None = None) -> bool:
    try:
        resolve(operand, seq, effects)
        return True
    except (ValueError, ZeroDivisionError):
        return False


def phrase(operand) -> str:
    """English for an operand: 4 -> '4', At(4) -> 'the number at position 4'.

    Composite operands fall back to their formula form — structure to
    string, one way, as always.
    """
    expr = sp.sympify(operand)
    if isinstance(expr, sp.Indexed) and expr.base == L:
        return f"the number at position {expr.indices[0]}"
    if _is_effect_ref(expr):
        return f"the count of numbers instruction {expr.indices[0]} changed"
    return str(expr)

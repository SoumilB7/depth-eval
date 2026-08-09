"""Operands — what x resolves from.

The operand of an operation is itself a SymPy expression built from:
- a literal:              Integer(4)
- a list reference:       At(4) == List[4] — the value at 0-indexed position 4
- an effect reference:    Changed(j) — see below
- the element's position: P (prints `p`) — each element's own 0-indexed index
- a companion reference:  B[P] — the matching number in the frozen companion
                          list B; B[3] — a fixed companion position
- any composition:        At(4) + 1, B[P] - P, Abs(At(2) - At(9)), ...

Scalar operands (no P, no B[...]) resolve ONCE per instruction to a single
integer. Per-element operands (containing P or B) resolve to a VECTOR — one
integer per position — still in one snapshot BEFORE the pass: List
references read the current list as it stands when the instruction executes,
never mid-pass. Either way, ops only ever receive plain integers.

The companion list B is generated from the same seeded generation as the
main list and is FROZEN — no instruction ever mutates it.

Positions are 0-indexed; a position outside the list (or companion) makes
the operand unresolvable (the question generator must avoid emitting it).
"""

import sympy as sp

L = sp.IndexedBase("List", integer=True)
B = sp.IndexedBase("B", integer=True)
P = sp.Symbol("p", integer=True, nonnegative=True)


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
    "last executed" means the most recent execution. Like At/List[p], it is
    native SymPy indexing, so it composes into every op (Max/Min included).
    """
    return _CHANGED[j]


def _is_effect_ref(e) -> bool:
    return isinstance(e, sp.Indexed) and e.base == _CHANGED


def _is_list_ref(e) -> bool:
    return isinstance(e, sp.Indexed) and e.base == L


def _is_companion_ref(e) -> bool:
    return isinstance(e, sp.Indexed) and e.base == B


def is_elementwise(operand) -> bool:
    """Whether the operand resolves per element (uses the position symbol P).

    B refs alone don't make an operand per-element: B[3] is a fixed
    companion position, resolved once like any scalar.
    """
    return sp.sympify(operand).has(P)


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


def _indexed_lookup(values: list[int], name: str):
    def lookup(ref: sp.Indexed) -> sp.Integer:
        idx = ref.indices[0]
        if not idx.is_Integer:
            raise ValueError(f"non-integer position {idx} in {name} reference")
        i = int(idx)
        if not 0 <= i < len(values):
            raise ValueError(f"position {i} out of range 0..{len(values) - 1} in {name}")
        return sp.Integer(values[i])

    return lookup


def _collapse(expr, seq, effects, companion) -> int:
    """Fully resolve an expression with concrete indices to an integer."""

    def lookup_effect(ref: sp.Indexed) -> sp.Integer:
        j = int(ref.indices[0])
        if effects is None or j not in effects:
            raise ValueError(f"instruction {j} has not executed — {expr} unresolvable")
        return sp.Integer(effects[j])

    result = expr.replace(_is_list_ref, _indexed_lookup(seq, "List"))
    if any(_is_companion_ref(e) for e in result.atoms(sp.Indexed)):
        if companion is None:
            raise ValueError(f"operand {expr} references B but no companion list exists")
        result = result.replace(_is_companion_ref, _indexed_lookup(companion, "B"))
    result = result.replace(_is_effect_ref, lookup_effect)
    if result.is_Integer is not True:
        raise ValueError(f"operand {expr} did not resolve to an integer")
    return int(result)


def resolve(
    operand,
    seq: list[int],
    effects: dict[int, int] | None = None,
    companion: list[int] | None = None,
) -> int:
    """Collapse a SCALAR operand to one integer against the current list."""
    expr = sp.sympify(operand)
    if is_elementwise(expr):
        raise ValueError(f"operand {expr} is per-element — use resolve_elementwise")
    return _collapse(expr, seq, effects, companion)


def resolve_elementwise(
    operand,
    seq: list[int],
    effects: dict[int, int] | None = None,
    companion: list[int] | None = None,
) -> list[int]:
    """Resolve an operand to one integer PER POSITION, in one snapshot.

    Scalar operands broadcast their single value; per-element operands
    substitute each position into P and read B against the companion.
    """
    expr = sp.sympify(operand)
    if not is_elementwise(expr):
        return [_collapse(expr, seq, effects, companion)] * len(seq)
    return [_collapse(expr.subs(P, i), seq, effects, companion) for i in range(len(seq))]


def resolvable(
    operand,
    seq: list[int],
    effects: dict[int, int] | None = None,
    companion: list[int] | None = None,
) -> bool:
    try:
        resolve(operand, seq, effects, companion)
        return True
    except (ValueError, ZeroDivisionError):
        return False


def phrase(operand) -> str:
    """English for an operand: 4 -> '4', At(4) -> 'the number at position 4',
    P -> 'its own position', B[P] -> 'the matching number in list B'.

    Composite operands fall back to their formula form — structure to
    string, one way, as always.
    """
    expr = sp.sympify(operand)
    if _is_list_ref(expr):
        return f"the number at position {expr.indices[0]}"
    if _is_effect_ref(expr):
        return f"the count of numbers instruction {expr.indices[0]} changed"
    if expr == P:
        return "its own position"
    if _is_companion_ref(expr):
        if expr.indices[0] == P:
            return "the matching number in list B"
        return f"the number at position {expr.indices[0]} in list B"
    return str(expr)

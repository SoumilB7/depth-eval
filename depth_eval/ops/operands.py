"""Operands — what x resolves from.

Every reference is one shape:   APPLIER [ POSITION ]

    APPLIER   List    the live list, read at execution time
              Start   the list as it was at the very start (frozen)
              B       this line's private list (frozen)
              Pos     the positions themselves: 0, 1, 2, ... (frozen)
    POSITION  k       a fixed number            -> scalar, one x for all
              p       each element's own index  -> vector, one x per element
              p+1     an offset from its own    -> vector; off the end = undefined
              List[0] a position read from data -> resolved inside-out

Two shorthands, stated to the evaluated model as conventions:
    n  ≡ List[p]   ("the number")
    p  ≡ Pos[p]    ("its own position")

Other operand parts: a literal Integer(4); Changed(j), the count of numbers
instruction j changed (an effect reference — see below); and any SymPy
composition of these (List[1] + B[0], Abs(Start[p] - List[p]), ...).

Scalar operands (no p) resolve ONCE per instruction to a single integer.
Per-element operands (containing p) resolve to a VECTOR — one integer per
position — still in one snapshot BEFORE the pass: List references read the
list as it stands when the instruction executes, never mid-pass. Either
way, ops only ever receive plain integers.

The private list B is a random set of numbers attached to the line of text
it is written in: frozen, same length as the main list, born from the list
seed at a fixed offset. There is NO way to reference another line's list —
B always means "the list of the line this text is on"; the executor
supplies that list at resolution time.

Positions are 0-indexed. A position outside 0..length-1 — in any applier,
including an offset that runs off the end — makes the operand unresolvable
(no wrapping; the question generator must never emit it).
"""

import sympy as sp

L = sp.IndexedBase("List", integer=True)
START = sp.IndexedBase("Start", integer=True)
B = sp.IndexedBase("B", integer=True)
POS = sp.IndexedBase("Pos", integer=True)
P = sp.Symbol("p", integer=True, nonnegative=True)

_CHANGED = sp.IndexedBase("Changed", integer=True)

APPLIER_NAMES = {L: "the list", START: "the starting list", B: "this line's list B"}


def At(position) -> sp.Indexed:
    """The value at a position of the current list — List[position]."""
    return L[position]


def Changed(j: int) -> sp.Indexed:
    """The count of positions whose value changed when instruction j last
    executed (j is a 1-based instruction listing number). Prints Changed[j].

    An EFFECT reference: resolving it requires instruction j to have already
    executed, so it creates an exec dependency — the executor auto-holds the
    referencing instruction until j has run, past or future. With repeats,
    "last executed" means the most recent execution.
    """
    return _CHANGED[j]


def _is_effect_ref(e) -> bool:
    return isinstance(e, sp.Indexed) and e.base == _CHANGED


def _is_list_ref(e) -> bool:
    return isinstance(e, sp.Indexed) and e.base == L


def _is_companion_ref(e) -> bool:
    return isinstance(e, sp.Indexed) and e.base == B


def _is_start_ref(e) -> bool:
    return isinstance(e, sp.Indexed) and e.base == START


def _is_pos_ref(e) -> bool:
    return isinstance(e, sp.Indexed) and e.base == POS


def is_elementwise(operand) -> bool:
    """Whether the operand resolves per element (its position uses p)."""
    return sp.sympify(operand).has(P)


def uses_companion(operand) -> bool:
    """Whether the operand reads the instruction's private list B."""
    return any(_is_companion_ref(e) for e in sp.sympify(operand).atoms(sp.Indexed))


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


def position_form(index) -> str:
    """The POSITION form of an index expression: fixed | own | offset | indirect."""
    index = sp.sympify(index)
    if index.is_Integer:
        return "fixed"
    if index == P:
        return "own"
    if index.atoms(sp.Indexed):
        return "indirect"
    if index.has(P):
        return "offset"
    return "fixed"


def _lookup(ref: sp.Indexed, seq, effects, companion, original) -> sp.Integer:
    """Resolve one reference whose position is already a concrete integer."""
    if len(ref.indices) != 1:
        raise ValueError(f"reference {ref} takes exactly one position")
    i = int(ref.indices[0])
    base = ref.base
    if base == _CHANGED:
        if effects is None or i not in effects:
            raise ValueError(f"instruction {i} has not executed — {ref} unresolvable")
        return sp.Integer(effects[i])
    if base == L:
        values, name = seq, "the list"
    elif base == START:
        if original is None:
            raise ValueError(f"{ref} references the starting list but none was given")
        values, name = original, "the starting list"
    elif base == B:
        if companion is None:
            raise ValueError(f"{ref} references B but this instruction has no list")
        values, name = companion, "this line's list B"
    elif base == POS:
        values, name = list(range(len(seq))), "the positions"
    else:
        raise ValueError(f"unknown applier in {ref}")
    if not 0 <= i < len(values):
        raise ValueError(f"position {i} out of range 0..{len(values) - 1} in {name}")
    return sp.Integer(values[i])


def _collapse(expr, seq, effects, companion, original) -> int:
    """Fully resolve an expression to an integer. References resolve
    inside-out: any reference whose position is already concrete is
    replaced, repeatedly, so List[List[0]] works. companion is THIS
    instruction's private list (or None if it has none)."""
    result = expr
    for _ in range(16):  # nesting depth bound — far beyond any real operand
        ready = [r for r in result.atoms(sp.Indexed) if r.indices and r.indices[0].is_Integer]
        if not ready:
            break
        result = result.xreplace(
            {r: _lookup(r, seq, effects, companion, original) for r in ready}
        )
    left = result.atoms(sp.Indexed)
    if left:
        raise ValueError(f"unresolvable position in {sorted(map(str, left))} of {expr}")
    if result.is_Integer is not True:
        raise ValueError(f"operand {expr} did not resolve to an integer")
    return int(result)


def resolve(
    operand,
    seq: list[int],
    effects: dict[int, int] | None = None,
    companion: list[int] | None = None,
    original: list[int] | None = None,
) -> int:
    """Collapse a SCALAR operand to one integer against the current list."""
    expr = sp.sympify(operand)
    if is_elementwise(expr):
        raise ValueError(f"operand {expr} is per-element — use resolve_elementwise")
    return _collapse(expr, seq, effects, companion, original)


def resolve_elementwise(
    operand,
    seq: list[int],
    effects: dict[int, int] | None = None,
    companion: list[int] | None = None,
    original: list[int] | None = None,
) -> list[int]:
    """Resolve an operand to one integer PER POSITION, in one snapshot.

    Scalar operands broadcast their single value; per-element operands
    substitute each position into p and resolve from there.
    """
    expr = sp.sympify(operand)
    if not is_elementwise(expr):
        return [_collapse(expr, seq, effects, companion, original)] * len(seq)
    return [
        _collapse(expr.subs(P, i), seq, effects, companion, original)
        for i in range(len(seq))
    ]


def resolvable(
    operand,
    seq: list[int],
    effects: dict[int, int] | None = None,
    companion: list[int] | None = None,
    original: list[int] | None = None,
) -> bool:
    try:
        resolve(operand, seq, effects, companion, original)
        return True
    except (ValueError, ZeroDivisionError):
        return False


def _position_words(index) -> str:
    if index == P:
        return "its own position"
    return f"position {index}"


def phrase(operand) -> str:
    """English for an operand, one pattern for every applier:
    'the number at position 3 of the list' / '... at its own position of
    the starting list' / '... of this line's list B'; Pos[p] -> 'its own
    position'. Composites fall back to their formula — structure to
    string, one way, as always."""
    expr = sp.sympify(operand)
    if _is_effect_ref(expr):
        return f"the count of numbers instruction {expr.indices[0]} changed"
    if expr == P:
        return "its own position"
    if _is_pos_ref(expr):
        idx = expr.indices[0]
        return "its own position" if idx == P else f"the position number {idx}"
    if isinstance(expr, sp.Indexed) and expr.base in APPLIER_NAMES:
        return f"the number at {_position_words(expr.indices[0])} of {APPLIER_NAMES[expr.base]}"
    return str(expr)

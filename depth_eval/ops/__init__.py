"""Operation registry.

Registration is explicit — an op exists in the eval if and only if it is
listed here. Keys are canonical printed expressions; SymPy canonicalization
means two entries for the same function collide, and the assert catches it.
"""

from .arithmetic import ARITHMETIC_OPS
from .base import Gcd, Lcm, NumberOp, n, x
from .scope import (ALL, GATE_KINDS, SCOPE_KINDS, Scope, above, bigger_at, changed_more,
                    even, even_at, odd, odd_at, same_as, span, stride, touched, untouched)
from .operands import (
    At,
    B,
    Changed,
    P,
    POS,
    START,
    effect_refs,
    position_form,
    resolve_mask,
    scope_refs,
    is_elementwise,
    resolvable,
    resolve,
    resolve_elementwise,
)

NUMBER_OPS: dict[str, NumberOp] = {op.id: op for op in ARITHMETIC_OPS}
assert len(NUMBER_OPS) == len(ARITHMETIC_OPS), "duplicate op expression in registry"

__all__ = [
    "NumberOp",
    "NUMBER_OPS",
    "Gcd",
    "Lcm",
    "n",
    "x",
    "At",
    "B",
    "P",
    "POS",
    "START",
    "position_form",
    "Changed",
    "effect_refs",
    "is_elementwise",
    "resolve",
    "resolve_elementwise",
    "resolvable",
    "resolve_mask",
    "scope_refs",
    "Scope",
    "ALL",
    "SCOPE_KINDS",
    "GATE_KINDS",
    "even_at",
    "odd_at",
    "bigger_at",
    "changed_more",
    "stride",
    "span",
    "even",
    "odd",
    "above",
    "touched",
    "untouched",
    "same_as",
]

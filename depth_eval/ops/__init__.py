"""Operation registry.

Registration is explicit — an op exists in the eval if and only if it is
listed here. Keys are canonical printed expressions; SymPy canonicalization
means two entries for the same function collide, and the assert catches it.
"""

from .arithmetic import ARITHMETIC_OPS
from .base import Gcd, Lcm, NumberOp, n, x
from .scope import ALL, SCOPE_KINDS, Scope, above, even, odd, same_as, span, stride, touched, untouched
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
    "stride",
    "span",
    "even",
    "odd",
    "above",
    "touched",
    "untouched",
    "same_as",
]

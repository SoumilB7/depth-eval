"""Operation registry.

Registration is explicit — an op exists in the eval if and only if it is
listed here. No magic auto-discovery.
"""

from .arithmetic import ARITHMETIC_OPS
from .base import NumberOp

NUMBER_OPS: dict[str, NumberOp] = {op.name: op for op in ARITHMETIC_OPS}

__all__ = ["NumberOp", "NUMBER_OPS"]

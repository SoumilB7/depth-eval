"""Operation registry.

Registration is explicit — an op exists in the eval if and only if it is
listed here. No magic auto-discovery.
"""

from .arithmetic import (
    AbsDiff,
    Add,
    FloorAverage,
    FloorDivide,
    FloorDivideInto,
    Gcd,
    Lcm,
    Maximum,
    Minimum,
    Mod,
    ModInto,
    Multiply,
    Power,
    PowerInto,
    Replace,
    Subtract,
    SubtractFrom,
)
from .base import NumberOp

NUMBER_OPS: dict[str, NumberOp] = {
    op.name: op
    for op in [
        Add(),
        Subtract(),
        SubtractFrom(),
        Multiply(),
        FloorDivide(),
        FloorDivideInto(),
        Mod(),
        ModInto(),
        Power(),
        PowerInto(),
        Gcd(),
        Lcm(),
        Minimum(),
        Maximum(),
        AbsDiff(),
        FloorAverage(),
        Replace(),
    ]
}

__all__ = ["NumberOp", "NUMBER_OPS"]

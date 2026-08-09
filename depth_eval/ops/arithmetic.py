"""All mathematical functions of the number n with operand x.

A permutation is just a different expression — n - x and x - n are separate
entries. Commutative forms canonicalize inside SymPy, so a duplicate of the
same function cannot exist in the registry (the registry asserts this).
"""

import sympy as sp

from .base import Gcd, Lcm, NumberOp, n, x

ARITHMETIC_OPS = [
    NumberOp(n + x, "the number plus {x}", inverse="n - x"),
    NumberOp(n - x, "the number minus {x}", inverse="n + x"),
    NumberOp(x - n, "{x} minus the number", inverse="-n + x"),  # self-inverse
    NumberOp(n * x, "the number times {x}", inverse="n/x"),
    NumberOp(sp.floor(n / x), "the number divided by {x}, rounded down"),
    NumberOp(sp.floor(x / n), "{x} divided by the number, rounded down"),
    NumberOp(sp.Mod(n, x), "the remainder when the number is divided by {x}"),
    NumberOp(sp.Mod(x, n), "the remainder when {x} is divided by the number"),
    NumberOp(n**x, "the number raised to the power {x}"),
    NumberOp(x**n, "{x} raised to the power of the number"),
    NumberOp(Gcd(n, x), "the greatest common divisor of the number and {x}"),
    NumberOp(Lcm(n, x), "the least common multiple of the number and {x}"),
    NumberOp(sp.Min(n, x), "the smaller of the number and {x}"),
    NumberOp(sp.Max(n, x), "the larger of the number and {x}"),
    NumberOp(sp.Abs(n - x), "the absolute difference between the number and {x}"),
    NumberOp(sp.floor((n + x) / 2), "the average of the number and {x}, rounded down"),
    NumberOp(x, "{x}"),
    # exact division — undefined unless divisible (evaluation catches 7/2).
    # Exists as multiply's inverse; the generator never draws it directly.
    NumberOp(n / x, "the number divided exactly by {x}", inverse="n*x"),
]

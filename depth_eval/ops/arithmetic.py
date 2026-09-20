"""All mathematical functions of the number n with operand x.

A permutation is just a different expression — n - x and x - n are separate
entries. Commutative forms canonicalize inside SymPy, so a duplicate of the
same function cannot exist in the registry (the registry asserts this).
"""

import sympy as sp

from .base import Gcd, Lcm, NumberOp, n, x

ARITHMETIC_OPS = [
    NumberOp(n + x, "the number plus {x}", inverse="n - x", family="linear"),
    NumberOp(n - x, "the number minus {x}", inverse="n + x", family="linear"),
    NumberOp(x - n, "{x} minus the number", inverse="-n + x", family="linear"),  # self-inverse
    NumberOp(n * x, "the number times {x}", inverse="n/x", family="scaling"),
    NumberOp(sp.floor(n / x), "the number divided by {x}, rounded down", family="shrinking"),
    NumberOp(sp.floor(x / n), "{x} divided by the number, rounded down", family="shrinking"),
    NumberOp(sp.Mod(n, x), "the remainder when the number is divided by {x}", family="shrinking"),
    NumberOp(sp.Mod(x, n), "the remainder when {x} is divided by the number", family="shrinking"),
    NumberOp(n**x, "the number raised to the power {x}", family="scaling"),
    NumberOp(x**n, "{x} raised to the power of the number", family="scaling"),
    NumberOp(Gcd(n, x), "the greatest common divisor of the number and {x}", family="shrinking"),
    NumberOp(Lcm(n, x), "the least common multiple of the number and {x}", family="scaling"),
    NumberOp(sp.Min(n, x), "the smaller of the number and {x}", family="shrinking"),
    NumberOp(sp.Max(n, x), "the larger of the number and {x}", family="shrinking"),
    NumberOp(sp.Abs(n - x), "the absolute difference between the number and {x}", family="shrinking"),
    NumberOp(sp.floor((n + x) / 2), "the average of the number and {x}, rounded down", family="shrinking"),
    NumberOp(x, "{x}", family="shrinking"),
    # exact division — undefined unless divisible (evaluation catches 7/2).
    # Exists as multiply's inverse; the generator never draws it directly.
    NumberOp(n / x, "the number divided exactly by {x}", inverse="n*x"),
]

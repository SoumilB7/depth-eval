"""All mathematical functions on a number n with an operand x.

Each op is a NumberOp instance. Non-commutative functions appear in BOTH
orderings (subtract / subtract_from, floor_divide / floor_divide_into,
mod / mod_into, power / power_into) — each ordering is its own op.
Commutative functions (add, multiply, gcd, lcm, min, max, absolute
difference, average) appear once.
"""

import math

from .base import NumberOp

ARITHMETIC_OPS = [
    NumberOp("add", "the number plus {x}", lambda n, x: n + x),
    NumberOp("subtract", "the number minus {x}", lambda n, x: n - x),
    NumberOp("subtract_from", "{x} minus the number", lambda n, x: x - n),
    NumberOp("multiply", "the number times {x}", lambda n, x: n * x),
    NumberOp(
        "floor_divide",
        "the number divided by {x}, rounded down",
        lambda n, x: n // x,
        defined=lambda n, x: x != 0,
    ),
    NumberOp(
        "floor_divide_into",
        "{x} divided by the number, rounded down",
        lambda n, x: x // n,
        defined=lambda n, x: n != 0,
    ),
    NumberOp(
        "mod",
        "the remainder when the number is divided by {x}",
        lambda n, x: n % x,
        defined=lambda n, x: x != 0,
    ),
    NumberOp(
        "mod_into",
        "the remainder when {x} is divided by the number",
        lambda n, x: x % n,
        defined=lambda n, x: n != 0,
    ),
    NumberOp(
        "power",
        "the number raised to the power {x}",
        lambda n, x: n**x,
        defined=lambda n, x: x >= 0,
    ),
    NumberOp(
        "power_into",
        "{x} raised to the power of the number",
        lambda n, x: x**n,
        defined=lambda n, x: n >= 0,
    ),
    NumberOp(
        "gcd",
        "the greatest common divisor of the number and {x}",
        lambda n, x: math.gcd(n, x),
    ),
    NumberOp(
        "lcm",
        "the least common multiple of the number and {x}",
        lambda n, x: math.lcm(n, x),
    ),
    NumberOp("minimum", "the smaller of the number and {x}", lambda n, x: min(n, x)),
    NumberOp("maximum", "the larger of the number and {x}", lambda n, x: max(n, x)),
    NumberOp(
        "abs_diff",
        "the absolute difference between the number and {x}",
        lambda n, x: abs(n - x),
    ),
    NumberOp(
        "floor_average",
        "the average of the number and {x}, rounded down",
        lambda n, x: (n + x) // 2,
    ),
    NumberOp("replace", "{x}", lambda n, x: x),
]

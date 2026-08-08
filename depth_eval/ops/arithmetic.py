"""All mathematical functions on a number n with an operand x.

Non-commutative functions appear in BOTH orderings as separate classes
(Subtract / SubtractFrom, FloorDivide / FloorDivideInto, Mod / ModInto,
Power / PowerInto) — each ordering is its own operation.

Commutative functions (add, multiply, gcd, lcm, min, max, absolute
difference, average) need only one class.
"""

import math

from .base import NumberOp


class Add(NumberOp):
    name = "add"
    template = "the number plus {x}"

    def apply(self, n, x):
        return n + x


class Subtract(NumberOp):
    name = "subtract"
    template = "the number minus {x}"

    def apply(self, n, x):
        return n - x


class SubtractFrom(NumberOp):
    name = "subtract_from"
    template = "{x} minus the number"

    def apply(self, n, x):
        return x - n


class Multiply(NumberOp):
    name = "multiply"
    template = "the number times {x}"

    def apply(self, n, x):
        return n * x


class FloorDivide(NumberOp):
    name = "floor_divide"
    template = "the number divided by {x}, rounded down"

    def apply(self, n, x):
        return n // x

    def defined_for(self, n, x):
        return x != 0


class FloorDivideInto(NumberOp):
    name = "floor_divide_into"
    template = "{x} divided by the number, rounded down"

    def apply(self, n, x):
        return x // n

    def defined_for(self, n, x):
        return n != 0


class Mod(NumberOp):
    name = "mod"
    template = "the remainder when the number is divided by {x}"

    def apply(self, n, x):
        return n % x

    def defined_for(self, n, x):
        return x != 0


class ModInto(NumberOp):
    name = "mod_into"
    template = "the remainder when {x} is divided by the number"

    def apply(self, n, x):
        return x % n

    def defined_for(self, n, x):
        return n != 0


class Power(NumberOp):
    name = "power"
    template = "the number raised to the power {x}"

    def apply(self, n, x):
        return n**x

    def defined_for(self, n, x):
        return x >= 0


class PowerInto(NumberOp):
    name = "power_into"
    template = "{x} raised to the power of the number"

    def apply(self, n, x):
        return x**n

    def defined_for(self, n, x):
        return n >= 0


class Gcd(NumberOp):
    name = "gcd"
    template = "the greatest common divisor of the number and {x}"

    def apply(self, n, x):
        return math.gcd(n, x)


class Lcm(NumberOp):
    name = "lcm"
    template = "the least common multiple of the number and {x}"

    def apply(self, n, x):
        return math.lcm(n, x)


class Minimum(NumberOp):
    name = "minimum"
    template = "the smaller of the number and {x}"

    def apply(self, n, x):
        return min(n, x)


class Maximum(NumberOp):
    name = "maximum"
    template = "the larger of the number and {x}"

    def apply(self, n, x):
        return max(n, x)


class AbsDiff(NumberOp):
    name = "abs_diff"
    template = "the absolute difference between the number and {x}"

    def apply(self, n, x):
        return abs(n - x)


class FloorAverage(NumberOp):
    name = "floor_average"
    template = "the average of the number and {x}, rounded down"

    def apply(self, n, x):
        return (n + x) // 2


class Replace(NumberOp):
    name = "replace"
    template = "{x}"

    def apply(self, n, x):
        return x

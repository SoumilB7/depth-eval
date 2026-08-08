"""Number operations as SymPy expressions.

An op IS a SymPy expression in the integer symbols n (the number) and x (the
operand). The structure is the identity: the registry key is the canonical
printed form of the expression (structure -> string, one way only — nothing
is ever parsed back from a string).

Evaluation is exact symbolic substitution — no floats anywhere, so values of
any size stay exact. An op is undefined at a point when substitution raises
ZeroDivisionError or yields a non-integer (zoo, nan, 7**-1 = 1/7, ...);
`defined_for` reports this and the question generator must avoid the point.

Semantics (SymPy's, which match Python's):
- floor(a/b) == a // b  (rounds toward negative infinity)
- Mod(a, b)  == a % b   (sign follows the divisor)
- 0**0 == 1
"""

import math
from dataclasses import dataclass

import sympy as sp

from .operands import phrase as operand_phrase

n = sp.Symbol("n", integer=True)
x = sp.Symbol("x", integer=True)


class Gcd(sp.Function):
    """Integer gcd, symbolic until both args are concrete integers.

    (sympy.gcd on symbols does polynomial gcd — gcd(n, x) == 1 — hence this.)
    """

    @classmethod
    def eval(cls, a, b):
        if a.is_Integer and b.is_Integer:
            return sp.Integer(math.gcd(int(a), int(b)))


class Lcm(sp.Function):
    """Integer lcm, symbolic until both args are concrete integers."""

    @classmethod
    def eval(cls, a, b):
        if a.is_Integer and b.is_Integer:
            return sp.Integer(math.lcm(int(a), int(b)))


@dataclass(frozen=True)
class NumberOp:
    """One operation: a SymPy expression plus its English phrase.

    - expr: the function of n and x. Its canonical printed form (`id`) is
      the op's identity everywhere (registry, specs, logs).
    - phrase: English for the NEW VALUE, `{x}` as operand placeholder.
      Instruction sentences show both renders, e.g.
      "Replace every number with the number times 4 (4*n)".
    """

    expr: sp.Expr
    phrase: str

    @property
    def id(self) -> str:
        return str(self.expr)

    def _eval(self, nv: int, xv: int) -> sp.Basic:
        # x substitutes BEFORE n: a zero divisor must be undefined for every
        # n, but n-first lets SymPy short-circuit (Mod(0, x) -> 0) and make
        # e.g. 0 mod 0 look defined.
        try:
            return self.expr.subs(x, xv).subs(n, nv)
        except ZeroDivisionError:
            return sp.nan

    def defined_for(self, nv: int, xv: int) -> bool:
        return self._eval(nv, xv).is_Integer is True

    def apply(self, nv: int, xv: int) -> int:
        # Hard boundary: ops only ever receive plain integers. References
        # (At/L[p]) are resolved by the executor BEFORE anything reaches here.
        if type(nv) is not int or type(xv) is not int:
            raise TypeError(
                f"NumberOp.apply takes plain ints, got n={nv!r}, x={xv!r} — "
                "resolve operands first"
            )
        result = self._eval(nv, xv)
        if result.is_Integer is not True:
            raise ValueError(f"{self.id} is undefined at n={nv}, x={xv}")
        return int(result)

    def formula(self, operand) -> str:
        """The expression with the operand filled in for x.

        The operand may be a literal int or any operand expression, e.g.
        At(4) — giving 'floor(n/7)' or 'floor(n/At(4))'.
        """
        return str(self.expr.subs(x, sp.sympify(operand)))

    def render(self, operand) -> str:
        """Both renders: English phrase, formula in parentheses."""
        return f"{self.phrase.format(x=operand_phrase(operand))} ({self.formula(operand)})"

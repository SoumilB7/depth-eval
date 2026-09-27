"""The two tools a solver may use — a calculator and a bulk calculator.

Ruling (Soumil, 2026-09-26): the model under test may offload ARITHMETIC,
never execution. These are pure functions of the numbers the model hands
them: no state, no files, no code, no route to the engine's questions or
answers. What the eval measures stays the same — holding the state of a
chain of instructions — minus the arithmetic slips.

Semantics are the engine's own: every value is a SymPy number and every
function is the one the ground truth uses (`floor`, `Mod`, `Gcd`, `Lcm`,
`Min`, `Max`, `Abs`), so a calculator answer can never disagree with the
grader. An expression is read with Python's `ast` against a whitelist and
built node by node — nothing is ever `eval`-ed. A result that is not an
integer (7/2, anything over zero) is an error, as it is in the engine.
Guards keep one call cheap: expression length, list length, digit count.
"""

import ast
import math
from dataclasses import dataclass
from typing import Callable

import sympy as sp

from depth_eval.ops import Gcd, Lcm

MAX_EXPRESSION = 2000  # characters
MAX_LIST = 1000        # positions in one bulk call
MAX_DIGITS = 10000     # digits in any intermediate value


class CalculatorError(ValueError):
    """What the model is told when a call cannot be answered."""


# name (case-insensitive) -> (arity, SymPy function); None arity = one or more
_FUNCTIONS = {
    "floor": (1, sp.floor),
    "abs": (1, sp.Abs),
    "mod": (2, sp.Mod),
    "gcd": (2, Gcd),
    "lcm": (2, Lcm),
    "min": (None, sp.Min),
    "max": (None, sp.Max),
}


def _bounded(value: sp.Basic) -> sp.Basic:
    if value.is_Integer and int(value).bit_length() > MAX_DIGITS * 3.33:
        raise CalculatorError(f"a value exceeds {MAX_DIGITS} digits")
    return value


def _nonzero(value: sp.Basic) -> sp.Basic:
    if value == 0:
        raise CalculatorError("division by zero")
    return value


def _power(base: sp.Basic, exponent: sp.Basic) -> sp.Basic:
    if not exponent.is_Integer:
        raise CalculatorError("an exponent must be an integer")
    if base == 0 and exponent < 0:
        raise CalculatorError("division by zero")
    if base.is_Integer and abs(base) > 1 and abs(int(exponent)) * math.log10(abs(int(base))) > MAX_DIGITS:
        raise CalculatorError(f"a value exceeds {MAX_DIGITS} digits")
    return base**exponent


_BINARY = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / _nonzero(b),
    ast.FloorDiv: lambda a, b: sp.floor(a / _nonzero(b)),
    ast.Mod: lambda a, b: sp.Mod(a, _nonzero(b)),
    ast.Pow: _power,
}


def _value(node: ast.AST, names: dict[str, int]) -> sp.Basic:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return _bounded(sp.Integer(node.value))
    if isinstance(node, ast.Name):
        if node.id not in names:
            available = ", ".join(names) or "none — use numbers only"
            raise CalculatorError(f"unknown name {node.id!r} (available: {available})")
        return sp.Integer(names[node.id])
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        operand = _value(node.operand, names)
        return -operand if isinstance(node.op, ast.USub) else operand
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _value(node.left, names), _value(node.right, names)
        return _bounded(_BINARY[type(node.op)](left, right))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        known = _FUNCTIONS.get(node.func.id.lower())
        if known is None:
            raise CalculatorError(
                f"unknown function {node.func.id!r} (available: floor, Mod, Gcd, Lcm, Min, Max, Abs)")
        arity, function = known
        args = [_value(a, names) for a in node.args]
        if (arity is None and not args) or (arity is not None and len(args) != arity):
            raise CalculatorError(f"{node.func.id} takes {arity or 'one or more'} argument(s)")
        return _bounded(function(*args))
    raise CalculatorError(f"not allowed in an expression: {ast.unparse(node)!r}")


def evaluate(expression: str, names: dict[str, int] | None = None) -> int:
    """One integer expression, exactly. Raises CalculatorError."""
    if not isinstance(expression, str) or not expression.strip():
        raise CalculatorError("expression must be a non-empty string")
    if len(expression) > MAX_EXPRESSION:
        raise CalculatorError(f"expression longer than {MAX_EXPRESSION} characters")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as e:
        raise CalculatorError(f"cannot read the expression: {e.msg}") from None
    try:
        result = _value(tree.body, names or {})
    except ZeroDivisionError:  # SymPy raises it for Mod(a, 0)
        raise CalculatorError("division by zero") from None
    if result.is_Integer is not True:
        raise CalculatorError(f"the result {result} is not an integer")
    return int(result)


def _integers(values, what: str) -> list[int]:
    if not isinstance(values, list) or not all(type(v) is int for v in values):
        raise CalculatorError(f"{what} must be a list of integers")
    if len(values) > MAX_LIST:
        raise CalculatorError(f"{what} longer than {MAX_LIST}")
    return values


def _calculate(args: dict) -> str:
    return str(evaluate(args.get("expression")))


def _bulk_calculate(args: dict) -> str:
    n = _integers(args.get("n"), "n")
    x = args.get("x")
    if x is not None and len(_integers(x, "x")) != len(n):
        raise CalculatorError("x must have the same length as n")
    results = []
    for p, value in enumerate(n):
        names = {"n": value, "p": p} | ({"x": x[p]} if x is not None else {})
        try:
            results.append(evaluate(args.get("expression"), names))
        except CalculatorError as e:
            raise CalculatorError(f"position {p}: {e}") from None
    return str(results)


@dataclass(frozen=True)
class Tool:
    """One tool a solver may call: its wording, its input shape, its work."""

    name: str
    description: str
    input_schema: dict
    work: Callable[[dict], str]

    def run(self, args) -> str:
        """The answer text for one call. Raises CalculatorError."""
        if not isinstance(args, dict):
            raise CalculatorError("input must be an object")
        return self.work(args)

    def definition(self) -> dict:
        return {"name": self.name, "description": self.description,
                "input_schema": self.input_schema}


_ARITHMETIC = (
    "Integers only, exact, any size. Operators: + - * / ** and parentheses; "
    "// is division rounded down, % is the remainder. Functions: floor(a/b) "
    "rounds down (toward minus infinity), Mod(a, b) is the remainder with the "
    "sign of b, Gcd(a, b) and Lcm(a, b) are never negative (Gcd(a, 0) = |a|, "
    "Lcm(a, 0) = 0), Min, Max, Abs. A result that is not an integer (such as "
    "7/2) or a division by zero is an error."
)

CALCULATOR = Tool(
    name="calculator",
    description="Evaluate one arithmetic expression and return its value. " + _ARITHMETIC,
    input_schema={
        "type": "object",
        "properties": {"expression": {"type": "string", "description": "e.g. floor(-7/2) + Mod(47, 5)"}},
        "required": ["expression"],
        "additionalProperties": False,
    },
    work=_calculate,
)

BULK_CALCULATOR = Tool(
    name="bulk_calculator",
    description=(
        "Evaluate one expression at every position of a list and return the list "
        "of results. Inside the expression, n is the value at that position of "
        "the list n, p is the position (counting from 0), and x is the value at "
        "the same position of the optional list x. " + _ARITHMETIC
    ),
    input_schema={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "e.g. Gcd(n, x) + p"},
            "n": {"type": "array", "items": {"type": "integer"}},
            "x": {"type": "array", "items": {"type": "integer"},
                  "description": "optional, same length as n"},
        },
        "required": ["expression", "n"],
        "additionalProperties": False,
    },
    work=_bulk_calculate,
)

# Explicit registry (coding norm #2): a tool exists iff it is listed here.
TOOLS: dict[str, Tool] = {tool.name: tool for tool in (CALCULATOR, BULK_CALCULATOR)}

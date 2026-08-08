"""The NumberOp type.

Classes in this project differentiate KINDS of things — they are typed
containers, not inheritance hierarchies. A NumberOp is one kind: a pure
mathematical function of one number `n` and one operand `x`, returning a new
integer. Individual operations are instances of this class, never subclasses.

Domain convention: everything is integers, always. Operations that could
leave the integers (division, average) floor instead, using Python floor
semantics (rounds toward negative infinity).
"""

from dataclasses import dataclass
from typing import Callable


def _everywhere(n: int, x: int) -> bool:
    return True


@dataclass(frozen=True)
class NumberOp:
    """A mathematical function (n, x) -> int.

    - name: stable snake_case identifier, used in registries and specs.
    - template: phrase describing the NEW VALUE, with `{x}` as the operand
      placeholder — e.g. "the number plus {x}". Sentence layers compose it,
      e.g. "Replace every number with " + template.
    - fn: the function itself.
    - defined: where the function is defined (default: everywhere). The
      question generator uses this to never emit an instruction that hits an
      undefined point (division by zero, negative exponent, ...).
    """

    name: str
    template: str
    fn: Callable[[int, int], int]
    defined: Callable[[int, int], bool] = _everywhere

    def apply(self, n: int, x: int) -> int:
        return self.fn(n, x)

    def defined_for(self, n: int, x: int) -> bool:
        return self.defined(n, x)

    def render(self, x: int) -> str:
        return self.template.format(x=x)

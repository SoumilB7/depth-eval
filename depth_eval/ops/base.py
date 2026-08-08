"""Base class for number operations.

A NumberOp is a pure mathematical function of one number `n` and one operand
`x`, returning a new integer. It carries its own human-language template so
wording and behaviour live side by side and cannot drift.

Domain convention: everything is integers, always. Operations that could
leave the integers (division, average) floor instead, using Python floor
semantics (rounds toward negative infinity).
"""

from abc import ABC, abstractmethod


class NumberOp(ABC):
    """A mathematical function (n, x) -> int.

    Class attributes every subclass must set:
    - name: stable snake_case identifier, used in registries and specs.
    - template: a phrase describing the NEW VALUE, with `{x}` as the operand
      placeholder — e.g. "the number plus {x}". Sentence layers compose it,
      e.g. "Replace every number with " + template.
    """

    name: str
    template: str

    @abstractmethod
    def apply(self, n: int, x: int) -> int:
        """Return the new value. Only called when defined_for(n, x) is True."""

    def defined_for(self, n: int, x: int) -> bool:
        """Whether the function is defined at (n, x). Default: everywhere.

        The question generator uses this to never emit an instruction that
        hits an undefined point (division by zero, negative exponent, ...).
        """
        return True

    def render(self, x: int) -> str:
        """The template with a concrete x filled in."""
        return self.template.format(x=x)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r})"

"""Moves — permutations of the list: values MOVE instead of changing.

The FORM=permute axis of the application mainframe, realized as its own
line kind (a move has no op and no operand — see MoveInstruction). Length
never changes. Positions are positions: scopes, B and Start stay
positional; contents move under them.

A Move yields a permutation sigma for the current list, where
new[i] = seq[sigma[i]]. Members:

    reverse()     sigma[i] = L-1-i          inverse: itself
    rotate(k)     sigma[i] = (i - k) % L    right by k; inverse: rotate(-k)
    swap(a, b)    exchange positions a, b   inverse: itself
    ascending()   stable sort, increasing   inverse: NONE as a definition
                                            (negate/flip reject it), but
                                            unwind still works — the
                                            executed permutation is recorded

Touched for a move = the positions whose value came from somewhere else
(sigma[i] != i); Changed counts value differences as everywhere. A move
whose permutation is the identity (rotate by a multiple of the length,
sorting an already-sorted list) moves nothing — a dead line, rejected like
an empty scope.
"""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Move:
    name: str            # reverse | rotate | swap | sort
    params: tuple        # (k,) for rotate, (a, b) for swap, () otherwise
    phrase: str          # "Rotate the list right by 2"
    formula: str         # "rotate(2)"
    sigma: Callable      # list[int] -> permutation: new[i] = seq[sigma[i]]

    def inverse(self) -> "Move | None":
        if self.name == "sort":
            return None
        if self.name == "rotate":
            return rotate(-self.params[0])
        return self  # reverse and swap are their own inverses


def reverse() -> Move:
    return Move("reverse", (), "Reverse the list", "reverse",
                lambda seq: list(range(len(seq) - 1, -1, -1)))


def rotate(k: int) -> Move:
    return Move("rotate", (k,), f"Rotate the list right by {k}", f"rotate({k})",
                lambda seq: [(i - k) % len(seq) for i in range(len(seq))])


def swap(a: int, b: int) -> Move:
    def sigma(seq):
        out = list(range(len(seq)))
        out[a], out[b] = b, a
        return out
    return Move("swap", (a, b), f"Swap the numbers at positions {a} and {b}",
                f"swap({a}, {b})", sigma)


def ascending() -> Move:
    return Move("sort", (), "Sort the list in increasing order", "sort",
                lambda seq: sorted(range(len(seq)), key=lambda i: (seq[i], i)))


MOVE_NAMES = ("reverse", "rotate", "swap", "sort")

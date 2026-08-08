"""Operation definitions.

Every operation is a pure function (sequence, x) -> new sequence, where x is
the single generic operand. Nothing mutates in place, so a chain of ops can
be replayed step by step to produce a canonical trace later.

Conventions (fixed here so questions are never ambiguous):
- Positions are 1-indexed: "every 3rd number" means positions 3, 6, 9, ...
- "Even"/"odd" refer to a number's VALUE, not its position.
- mod uses Python semantics: result is always in [0, x) for x >= 1.
- Rotation is to the right: the last element wraps around to the front.

`template` is the human-language form of the instruction with `{x}`
substituted in — it is exactly what the model under eval will read, so it
must match the code's behaviour to the letter.
"""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Operation:
    name: str
    template: str
    apply: Callable[[list[int], int], list[int]]


def _add(seq, x):
    return [n + x for n in seq]


def _subtract(seq, x):
    return [n - x for n in seq]


def _multiply(seq, x):
    return [n * x for n in seq]


def _mod(seq, x):
    return [n % x for n in seq]


def _add_to_evens(seq, x):
    return [n + x if n % 2 == 0 else n for n in seq]


def _add_to_odds(seq, x):
    return [n + x if n % 2 != 0 else n for n in seq]


def _replace_every_xth(seq, x):
    return [x if (i + 1) % x == 0 else n for i, n in enumerate(seq)]


def _rotate_right(seq, x):
    if not seq:
        return []
    k = x % len(seq)
    return seq[-k:] + seq[:-k]


OPS: dict[str, Operation] = {
    op.name: op
    for op in [
        Operation("add", "Add {x} to every number", _add),
        Operation("subtract", "Subtract {x} from every number", _subtract),
        Operation("multiply", "Multiply every number by {x}", _multiply),
        Operation(
            "mod",
            "Replace every number with its remainder when divided by {x}",
            _mod,
        ),
        Operation("add_to_evens", "Add {x} to every even number", _add_to_evens),
        Operation("add_to_odds", "Add {x} to every odd number", _add_to_odds),
        Operation(
            "replace_every_xth",
            "Replace every {x}th number with {x}",
            _replace_every_xth,
        ),
        Operation("rotate_right", "Rotate the list to the right by {x}", _rotate_right),
    ]
}

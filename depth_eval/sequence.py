"""Seeded starting-sequence generation.

The working object of the eval is a flat list of integers. It is always
produced from an explicit seed so any question can be recreated exactly.
"""

import random


def make_sequence(seed: int, length: int = 100, low: int = 0, high: int = 50) -> list[int]:
    """Return a reproducible list of `length` integers in [low, high]."""
    rng = random.Random(seed)
    return [rng.randint(low, high) for _ in range(length)]

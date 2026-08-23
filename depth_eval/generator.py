"""Question generation — the random frequency generator.

Two seeds, two responsibilities, never mixed:

- list_seed        -> the DATA. One seeded stream produces the main list
                      first, then one private list B per instruction slot
                      at a fixed offset (draws (k*length)..((k+1)*length - 1)
                      for slot k). Pre-addressed: slot k's list is identical
                      whether or not the question ever reads it — exact
                      redo-ability. A list is surfaced in the question text
                      only on the line that reads it.
- instruction_seed -> the QUESTION. Every draw comes from this stream and
                      only this one, in this order per instruction slot:
                        1. CATEGORY  direct | relative   (the nomenclature)
                        2. KIND      within the category (weighted)
                        3. variant   e.g. fixed vs matching position (uniform)
                        4. numbers   op, positions, literals, targets
                        5. hold      one gate, then a target
                      The forced nomenclature IS the first probability
                      distribution of instruction creation; the kind tables
                      live in nomenclature.py and configs are validated
                      against them.

Same (list_seed, instruction_seed, steps, length, config) -> the same
Question, always. Candidate chains that fail validation are repaired
(blamed instructions re-drawn); the diversity floor re-rolls the chain —
rejections just consume more draws, so the outcome stays deterministic.
"""

import random
from dataclasses import dataclass, field

from .instructions import Instruction, Step, execute, render_question
from .meta import META_VERBS, MetaInstruction
from .nomenclature import CATEGORIES, DIRECT_KINDS, RELATIVE_KINDS, check_weights
from .ops import NUMBER_OPS, At, B, Changed, P, START
from .sequence import make_sequences
from .validation import validate


@dataclass(frozen=True)
class GeneratorConfig:
    """The frequency knobs of question generation.

    Deliberately NOT here: `steps` (chain length = depth) and `length`
    (list size = width). Those are the eval's independent variables — the
    capability surface is swept over them — so they belong to the run and
    are passed to generate().
    """

    low: int = 0
    high: int = 50
    literal_low: int = 1
    literal_high: int = 10
    # DRAW 1 — the nomenclature split
    category_weights: dict[str, int] = field(
        default_factory=lambda: {"direct": 75, "relative": 25}
    )
    # DRAW 2a — kind within DIRECT (what the line reads)
    direct_weights: dict[str, int] = field(
        default_factory=lambda: {
            "literal": 40,     # a plain number
            "live": 20,        # List[i]  — current value at a fixed position
            "origin": 15,      # Start[i] or Start[p]  (variant: uniform)
            "companion": 15,   # B[i] or B[p] — this line's private list
            "positional": 10,  # p — the element's own position
        }
    )
    # DRAW 2b — kind within RELATIVE (how the line couples to another)
    relative_weights: dict[str, int] = field(
        default_factory=lambda: {
            "effect": 100,     # Changed[j] operand — consumes j's effect
            "definition": 0,   # mirror | negate   (variant: uniform)
            "execution": 0,    # unwind
            "alter": 0,        # amplify | flip | rewrite (variant: uniform)
            "erase": 0,        # cancel
        }
    )
    hold_chance: float = 0.25
    include_powers: bool = False  # n**x / x**n explode under chaining
    # the output list must keep at least this fraction of distinct values
    min_distinct_fraction: float = 0.3
    max_attempts: int = 200

    def __post_init__(self) -> None:
        # weights must speak the nomenclature exactly — no silent typos
        check_weights("category_weights", self.category_weights, CATEGORIES)
        check_weights(
            "direct_weights",
            self.direct_weights,
            [k for k, drawn in DIRECT_KINDS.items() if drawn],
        )
        check_weights("relative_weights", self.relative_weights, RELATIVE_KINDS)


@dataclass(frozen=True)
class Question:
    """One fully-solved eval question — the complete artifact."""

    list_seed: int
    instruction_seed: int
    steps: int
    length: int
    config: GeneratorConfig
    start: list[int]
    companions: list[list[int]]  # companions[k-1] is instruction k's private list B
    instructions: list
    text: str                    # self-contained: lines show their B inline
    final: list[int]
    trace: list[Step]
    attempts: int  # repair/re-roll rounds until one chain passed all gates


def _weighted(rng: random.Random, weights: dict[str, int]) -> str:
    live = {k: w for k, w in weights.items() if w > 0}
    return rng.choices(list(live), weights=list(live.values()))[0]


def _direct_operand(rng: random.Random, config: GeneratorConfig, length: int):
    kind = _weighted(rng, config.direct_weights)
    if kind == "live":
        return At(rng.randint(0, length - 1))
    if kind == "origin":
        return START[P] if rng.random() < 0.5 else START[rng.randint(0, length - 1)]
    if kind == "companion":
        return B[P] if rng.random() < 0.5 else B[rng.randint(0, length - 1)]
    if kind == "positional":
        return P
    return rng.randint(config.literal_low, config.literal_high)


def _random_instruction(
    rng: random.Random, config: GeneratorConfig, steps: int, length: int,
    pool: list[str], number: int
):
    others = [j for j in range(1, steps + 1) if j != number]
    # DRAW 1: the nomenclature. A lone instruction has nothing to couple to.
    category = _weighted(rng, config.category_weights) if others else "direct"

    def hold():
        if others and rng.random() < config.hold_chance:
            return rng.choice(others)
        return None

    if category == "direct":
        op = NUMBER_OPS[rng.choice(pool)]
        operand = _direct_operand(rng, config, length)
        return Instruction(op, operand, hold_until_after=hold())

    kind = _weighted(rng, config.relative_weights)
    if kind == "effect":
        op = NUMBER_OPS[rng.choice(pool)]
        return Instruction(op, Changed(rng.choice(others)), hold_until_after=hold())
    verb = META_VERBS[rng.choice(RELATIVE_KINDS[kind][1])]
    target = rng.choice(others)
    operand = _direct_operand(rng, config, length) if verb.takes_operand else None
    return MetaInstruction(verb, target, operand=operand, hold_until_after=hold())


def _random_chain(
    rng: random.Random, config: GeneratorConfig, steps: int, length: int, pool: list[str]
) -> list:
    return [
        _random_instruction(rng, config, steps, length, pool, number)
        for number in range(1, steps + 1)
    ]


def generate(
    list_seed: int,
    instruction_seed: int,
    steps: int,
    length: int,
    config: GeneratorConfig = GeneratorConfig(),
) -> Question:
    """Produce one valid, non-degenerate, fully-solved Question.

    steps (depth) and length (width) are the run's independent variables;
    everything else about question flavour comes from config.
    """
    lists = make_sequences(list_seed, 1 + steps, length, config.low, config.high)
    start, companions = lists[0], lists[1:]
    rng = random.Random(instruction_seed)
    pool = [
        op_id
        for op_id in NUMBER_OPS
        if op_id != "n/x" and (config.include_powers or op_id not in ("n**x", "x**n"))
    ]
    floor = max(2, int(config.min_distinct_fraction * length))

    # Repair loop: whole-chain re-rolls die geometrically with depth, so on
    # validation failure only the BLAMED instructions are re-drawn (the
    # validator names them). Full re-roll only when there is no blame (the
    # diversity floor). Deterministic: repairs consume the instruction
    # stream in a fixed order, so the same identity always converges to the
    # same question.
    chain = _random_chain(rng, config, steps, length, pool)
    for attempt in range(1, config.max_attempts + 1):
        issues = validate(chain, start, companions)
        if issues:
            blamed = sorted(
                {i.instruction for i in issues if 1 <= i.instruction <= steps}
            )
            if blamed:
                for number in blamed:
                    chain[number - 1] = _random_instruction(
                        rng, config, steps, length, pool, number
                    )
            else:
                chain = _random_chain(rng, config, steps, length, pool)
            continue
        final, trace = execute(chain, start, companions)
        if len(set(final)) < floor:
            chain = _random_chain(rng, config, steps, length, pool)
            continue
        return Question(
            list_seed=list_seed,
            instruction_seed=instruction_seed,
            steps=steps,
            length=length,
            config=config,
            start=start,
            companions=companions,
            instructions=chain,
            text=render_question(chain, companions),
            final=final,
            trace=trace,
            attempts=attempt,
        )

    raise ValueError(
        f"no valid question within {config.max_attempts} attempts "
        f"(list_seed={list_seed}, instruction_seed={instruction_seed}) — "
        "loosen the config or change seeds"
    )

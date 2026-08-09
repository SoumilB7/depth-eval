"""Question generation — the random frequency generator.

Two seeds, two responsibilities, never mixed:

- list_seed        -> the DATA. One seeded stream produces the main list
                      first, then companion row k for instruction k at a
                      fixed offset (draws (k*length)..((k+1)*length - 1)).
                      Rows are pre-addressed: row k is identical whether or
                      not any question uses it — exact redo-ability.
- instruction_seed -> the QUESTION. Op choices, operand kinds (drawn by
                      weighted frequency), the numbers inside instructions,
                      and holds all come from this stream and only this one.

Same (list_seed, instruction_seed, config) -> the same Question, always.
Candidate chains that fail validation or the anti-degeneracy floor are
discarded and regenerated — rejections just consume more draws from the
instruction stream, so the outcome stays deterministic.
"""

import random
from dataclasses import dataclass, field

from .instructions import Instruction, Step, execute, render_question
from .meta import META_VERBS, MetaInstruction
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
    # relative frequency of each operand kind
    operand_weights: dict[str, int] = field(
        default_factory=lambda: {
            "literal": 30,     # a plain number
            "at": 15,          # List[i] — current value at a fixed position
            "at_start": 10,    # Start[i] — original value at a fixed position
            "at_companion": 10,  # B[k, i] — fixed spot in own companion row
            "changed": 15,     # Changed[j] — effect reference (auto-holds)
            "matching": 10,    # B[k, p] — own companion row, matching position
            "position": 10,    # p — the element's own position
        }
    )
    hold_chance: float = 0.25
    # relative frequency of meta verbs vs ordinary data instructions.
    # {"data": 100} alone means no metas AND changes no draw order — old
    # states keep producing identical questions.
    meta_weights: dict[str, int] = field(
        default_factory=lambda: {"data": 100}
    )
    include_powers: bool = False  # n**x / x**n explode under chaining
    # the output list must keep at least this fraction of distinct values
    min_distinct_fraction: float = 0.3
    max_attempts: int = 200


@dataclass(frozen=True)
class Question:
    """One fully-solved eval question — the complete artifact."""

    list_seed: int
    instruction_seed: int
    steps: int
    length: int
    config: GeneratorConfig
    start: list[int]
    companions: list[list[int]]  # row k-1 belongs to instruction k
    instructions: list[Instruction]
    text: str
    final: list[int]
    trace: list[Step]
    attempts: int  # candidates consumed until one passed all gates


def _random_operand(
    rng: random.Random, config: GeneratorConfig, steps: int, length: int, number: int
):
    kinds = list(config.operand_weights)
    kind = rng.choices(kinds, weights=list(config.operand_weights.values()))[0]
    if kind == "at":
        return At(rng.randint(0, length - 1))
    if kind == "at_start":
        return START[rng.randint(0, length - 1)]
    if kind == "at_companion":
        return B[number, rng.randint(0, length - 1)]
    if kind == "changed":
        others = [j for j in range(1, steps + 1) if j != number]
        if others:
            return Changed(rng.choice(others))
    if kind == "matching":
        return B[number, P]
    if kind == "position":
        return P
    return rng.randint(config.literal_low, config.literal_high)


def _random_instruction(
    rng: random.Random, config: GeneratorConfig, steps: int, length: int,
    pool: list[str], number: int
):
    meta_kinds = {k: w for k, w in config.meta_weights.items() if w > 0}
    others = [j for j in range(1, steps + 1) if j != number]
    kind = "data"
    if others and set(meta_kinds) != {"data"}:
        kind = rng.choices(list(meta_kinds), weights=list(meta_kinds.values()))[0]
    hold = None
    if kind == "data":
        op = NUMBER_OPS[rng.choice(pool)]
        operand = _random_operand(rng, config, steps, length, number)
        if others and rng.random() < config.hold_chance:
            hold = rng.choice(others)
        return Instruction(op, operand, hold_until_after=hold)
    verb = META_VERBS[kind]
    target = rng.choice(others)
    operand = (
        _random_operand(rng, config, steps, length, number)
        if verb.takes_operand
        else None
    )
    if others and rng.random() < config.hold_chance:
        hold = rng.choice(others)
    return MetaInstruction(verb, target, operand=operand, hold_until_after=hold)


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
        if config.include_powers or op_id not in ("n**x", "x**n")
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
            text=render_question(chain),
            final=final,
            trace=trace,
            attempts=attempt,
        )

    raise ValueError(
        f"no valid question within {config.max_attempts} attempts "
        f"(list_seed={list_seed}, instruction_seed={instruction_seed}) — "
        "loosen the config or change seeds"
    )

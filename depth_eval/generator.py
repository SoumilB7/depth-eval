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
                        3. variant   e.g. fixed vs own position (uniform)
                        4. numbers   op, positions, literals, targets
                        5. APPLICATION  how a data line lands (only its
                                        EXTENT — the scope — is drawn today)
                        6. hold      one gate, then a target
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

from .application import ALWAYS, ORDERS, TIMES_CHOICES, WHOLE, Application
from .instructions import Instruction, MoveInstruction, Step, execute, render_question
from .ops.moves import ascending, reverse, rotate, swap
from .meta import META_VERBS, MetaInstruction
from .nomenclature import CATEGORIES, DIRECT_KINDS, RELATIVE_KINDS, check_weights
from .ops.scope import (ALL, GATE_KINDS, SCOPE_KINDS, above, bigger_at, changed_more,
                        even, even_at, odd, odd_at, same_as, span, stride, touched, untouched)
from .ops import NUMBER_OPS, At, B, Changed, P, POS, START
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
            "origin": 15,      # Start[k] | Start[p]  (type fixed|own: uniform)
            "companion": 15,   # B[k] | B[p] — this line's private list
            "positional": 10,  # Pos[p] — the element's own position
            "move": 0,         # a permute line: reverse/rotate/swap/sort
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
    # DRAW 3 — the SCOPE of a data line (which positions it touches).
    # {"all": 100} alone means every line touches every number AND changes
    # no draw order — old states keep producing identical questions.
    scope_weights: dict[str, int] = field(
        default_factory=lambda: {
            "all": 100, "stride": 0, "span": 0, "value": 0, "touched": 0, "same": 0
        }
    )
    # DRAW 3b — TIMES: how many passes ("1" alone = no draw)
    times_weights: dict[str, int] = field(
        default_factory=lambda: {"1": 100, "2": 0, "3": 0}
    )
    # DRAW 3c — GATE: always | a value test | an effect test ("always" alone = no draw)
    gate_weights: dict[str, int] = field(
        default_factory=lambda: {"always": 100, "value": 0, "effect": 0}
    )
    # DRAW 3d — ORDER of a pass ("snapshot" alone = no draw; map lines only)
    order_weights: dict[str, int] = field(
        default_factory=lambda: {"snapshot": 100, "forward": 0, "backward": 0}
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
        check_weights("scope_weights", self.scope_weights, SCOPE_KINDS)
        check_weights("times_weights", self.times_weights, TIMES_CHOICES)
        check_weights("gate_weights", self.gate_weights, GATE_KINDS)
        check_weights("order_weights", self.order_weights, ORDERS)


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


def _direct_operand(rng: random.Random, config: GeneratorConfig, length: int, kind: str | None = None):
    """kind: pass the already-drawn direct kind; None draws one here
    (excluding "move" — an operand cannot be a permutation)."""
    if kind is None:
        kind = _weighted(rng, {k: w for k, w in config.direct_weights.items() if k != "move"})
    if kind == "live":
        return At(rng.randint(0, length - 1))
    if kind in ("origin", "companion"):
        applier = START if kind == "origin" else B
        own = rng.random() < 0.5  # type: own | fixed (uniform today)
        return applier[P] if own else applier[rng.randint(0, length - 1)]
    if kind == "positional":
        return POS[P]
    return rng.randint(config.literal_low, config.literal_high)


def _random_scope(rng: random.Random, config: GeneratorConfig, length: int, others: list[int]):
    if {k for k, w in config.scope_weights.items() if w > 0} == {"all"}:
        return ALL  # no draw: the stream is untouched
    kind = _weighted(rng, config.scope_weights)
    if kind == "stride":
        step = rng.randint(2, 4)
        return stride(step, rng.randint(0, step - 1), length, from_end=rng.random() < 0.5)
    if kind == "span":
        a = rng.randint(0, length - 2)
        return span(a, rng.randint(a + 1, length - 1))
    if kind == "value":
        pick = rng.randint(0, 2)
        return even() if pick == 0 else odd() if pick == 1 else above(
            rng.randint(config.literal_low, config.literal_high))
    if kind == "touched" and others:
        j = rng.choice(others)
        return touched(j) if rng.random() < 0.5 else untouched(j)
    if kind == "same" and others:
        return same_as(rng.choice(others))
    return ALL


def _random_gate(rng: random.Random, config: GeneratorConfig, length: int, others: list[int]):
    if {k for k, w in config.gate_weights.items() if w > 0} == {"always"}:
        return ALWAYS  # no draw: the stream is untouched
    kind = _weighted(rng, config.gate_weights)
    if kind == "value":
        pick, i = rng.randint(0, 2), rng.randint(0, length - 1)
        if pick == 0:
            return even_at(i)
        if pick == 1:
            return odd_at(i)
        return bigger_at(i, rng.randint(config.literal_low, config.literal_high))
    if kind == "effect" and others:
        return changed_more(rng.choice(others), rng.randint(0, length // 2))
    return ALWAYS


def _random_application(
    rng: random.Random, config: GeneratorConfig, length: int, others: list[int],
    extent_allowed: bool = True, order_allowed: bool = True,
) -> Application:
    """HOW a data line lands: EXTENT, TIMES, GATE, ORDER (map lines only).
    All-default weight tables consume no draws at all."""
    scope = _random_scope(rng, config, length, others) if extent_allowed else ALL
    times = 1
    if {k for k, w in config.times_weights.items() if w > 0} != {"1"}:
        times = int(_weighted(rng, config.times_weights))
    gate = _random_gate(rng, config, length, others)
    order = "snapshot"
    if order_allowed and {k for k, w in config.order_weights.items() if w > 0} != {"snapshot"}:
        order = _weighted(rng, config.order_weights)
    if scope is ALL and times == 1 and gate is ALWAYS and order == "snapshot":
        return WHOLE
    return Application(extent=scope, times=times, gate=gate, order=order)


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
        kind = _weighted(rng, {k: v for k, v in config.direct_weights.items()})
        if kind == "move":
            pick = rng.randint(0, 3)
            if pick == 0:
                move = reverse()
            elif pick == 1:
                move = rotate(rng.randint(1, length - 1))
            elif pick == 2:
                a = rng.randint(0, length - 1)
                move = swap(a, rng.choice([j for j in range(length) if j != a]))
            else:
                move = ascending()
            how = _random_application(rng, config, length, others,
                                      extent_allowed=move.name != "swap",
                                      order_allowed=False)
            return MoveInstruction(move, hold_until_after=hold(), application=how)
        op = NUMBER_OPS[rng.choice(pool)]
        operand = _direct_operand(rng, config, length, kind)
        how = _random_application(rng, config, length, others)
        return Instruction(op, operand, hold_until_after=hold(), application=how)

    kind = _weighted(rng, config.relative_weights)
    if kind == "effect":
        op = NUMBER_OPS[rng.choice(pool)]
        operand = Changed(rng.choice(others))
        how = _random_application(rng, config, length, others)
        return Instruction(op, operand, hold_until_after=hold(), application=how)
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

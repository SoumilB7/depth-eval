# depth-eval

**How many chained instructions can a model hold in its head?**

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![SymPy](https://img.shields.io/badge/math-SymPy-green) ![Deterministic](https://img.shields.io/badge/runs-fully%20seeded-orange) ![Tests](https://img.shields.io/badge/tests-64%20passing-brightgreen)

```
seeds ──► generator ──► question ──► model ──► stage log ──► graded stage by stage
                           │                                        ▲
                           └──► engine ──► exact truth at every stage┘
```

A list of numbers. A numbered chain of instructions that change it — some
wait for later lines, some read what another line did, some rewrite or
cancel other lines. The model works through them by reasoning alone and
writes down the list after **every** instruction. We know the exact list at
every stage, so a wrong answer tells us precisely *where* the model fell
off, and *what kind of line* it fell on.

## Where it stands

| model | questions | exact | notes |
|---|---|---|---|
| Claude Fable 5.1 | 48 (3 configs × 5/10/20/40 lines × 4 seeds) | **48 / 48** | all 900 stages right |
| Claude Haiku 4.5 | 36 (3 configs × 10/20/40 lines × 4 seeds) | **18 / 36** | drops with depth; most misses miscount "how many numbers line j changed" |

Both runs at list length 10, by write-only solvers that cannot read files
or run code. The eval now separates models; the next step is wider lists
(length 20, 40), longer chains, and independent seeds per depth before a
multi-model benchmark.

## What it does

- **Generate.** Seeded questions from weighted, plain-JSON configs. Same
  seeds, same question, forever.
- **Validate.** Eighteen named error states — circular waits, a line using
  a result that doesn't exist yet, an edit of a line that already ran,
  division by zero, a line that wipes the whole list, a list that goes
  flat, too many do-nothing lines. A broken chain cannot become a question;
  the generator repairs the blamed line instead.
- **Solve.** Numbered order plus holds — the only thing that moves a line.
  A static schedule, then exact symbolic replay: integers only, no floats,
  any size.
- **Grade.** The model's answer is a JSON stage log. The harness compares
  it with the truth stage by stage: first wrong stage, what kind of
  mistake (order / value / count / final / malformed), and a full
  side-by-side report of every stage.

## Quick start

```bash
pip install sympy python-dotenv "anthropic>=1.0"     # anthropic only for --agent claude
```

```python
from depth_eval import generate, load_config, render_prompt

q = generate(list_seed=42, instruction_seed=37, steps=10, length=10,
             config=load_config("deep"))
print(render_prompt(q.start, q.instructions, q.companions))  # exactly what a model is sent
print(q.final)                                               # the answer we grade against
```

`steps` is depth, `length` is width — sweep both, get a capability surface.

## What a line can do

Every example starts from `[4, 9, 2, 7]`; every result comes from the engine.

```
direct     add 3                                         → [7, 12, 5, 10]
           add the number at position 0 (the list now)  → [8, 13, 6, 11]
           add each number's own position                → [4, 10, 4, 10]
           reverse / sort (values move, none changes)    → [7, 2, 9, 4] / [2, 4, 7, 9]

relative   ×10, then add how many numbers line 1 changed → [44, 94, 24, 74]
           add 5, then do the opposite of line 1          → [4, 9, 2, 7]
           ×3, then undo what line 1 did                  → [4, 9, 2, 7]
           "from now on line 2 uses double" (+3 → +6)     → [10, 15, 8, 13]
           "line 2 does nothing"                          → line 2 never happens

how it     only positions 1–2, ×10                        → [4, 90, 20, 7]
lands      add position 0, twice over (re-read: +4, +8)   → [16, 21, 14, 19]
           only if position 0 is even: add 100            → [104, 109, 102, 107]
           one number at a time, left to right            → a running sum

when       "hold until line k has executed" — runs right after k
```

References resolve **when the line runs** — "the number at position 3"
means position 3 *at that moment*. Meta lines can aim at meta lines ("do
line 5 again" where line 5 doubles line 3), so meaning can pass through a
chain of lines before it reaches a number. Every question reports how deep
its references chain (**R**) and how far they reach (**d**).

Plain-words walkthrough: `z-docs/design/in-plain-words.md`; one example per
kind: `z-docs/design/example-run.md`.

## Difficulty as data

Question flavour lives in [configs/](configs/) as plain JSON — `shallow`,
`default`, `deep` ship; drop in your own state and select it by name.

| dial | shallow | default | deep |
|---|---|---|---|
| relative lines (configured) | 25% | 50% | 65% |
| relative kinds | effect, mirror/negate, undo | all | all |
| op families linear · scaling · shrinking | 40 · 10 · 50 | 40 · 10 · 50 | 40 · 10 · 50 |
| reach near · mid · far / chain bias | 1·1·1 / 0 | 1·1·2 / .5 | 1·1·3 / .8 |
| unneeded holds | 5% | 10% | 15% |

Every question keeps variety in the list at every stage and at most 15% of
lines that change nothing, so a 40-line question is really 40 lines of work.

## Running a model

```bash
cp .env.example .env
python main.py --agent claude --spec deep-s20-L10-ls1-is11     # API solver (needs ANTHROPIC_API_KEY)
python main.py --agent reply  --spec deep-s20-L10-ls1-is11     # grade a reply file from ANSWERS_DIR
python main.py --agent <recording>.recording.jsonl             # replay and re-grade, no model call
```

A run spec is `{config}-s{steps}-L{length}-ls{list_seed}-is{instruction_seed}`.
The API solver gets the prompt and two calculators — nothing else, no
retries. Every run is recorded (JSONL, with the per-stage report) and
summarised in a scorecard under `recordings/`; a failure on our side is
logged as an error, never scored.

## Under the hood

```
depth_eval/
├── ops/             18 operations as SymPy expressions, references, scopes, moves
├── meta/            the verbs — instructions about instructions
├── lines.py         line kinds + the exact wording and prompt
├── definitions.py   what each line currently means (edits change this, never the text)
├── application.py   how a line lands: scope · times · gate · order
├── dag.py           holds → static schedule
├── instructions.py  execution + event trace
├── validation.py    the eighteen error states
├── nomenclature.py  direct / relative vocabulary, R and d
└── generator.py     seeded generation with targeted repair
harness/             environment · agents · grading · calculators · recordings · scorecard
```

A question is identified by `(list_seed, instruction_seed, steps, length,
config, code version)` — nothing else. Everything downstream is a pure
function of that tuple.

## Testing

`python -m pytest` runs 64 tests (engine + harness). A git-ignored audit
(`testruns/audit.py`) generates the 48-cell grid, re-validates every
question, checks determinism, schedule and state threading, and reports
effective depth per cell.

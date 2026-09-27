# depth-eval

**How many chained instructions can a model hold in its head?**

![version](https://img.shields.io/badge/benchmark-v1.0.0-blue) ![questions](https://img.shields.io/badge/questions-360-orange) ![Python](https://img.shields.io/badge/Python-3.10+-blue) ![license](https://img.shields.io/badge/license-MIT%20%7C%20CC%20BY%204.0-lightgrey)

A model gets a list of numbers and a numbered chain of instructions that
change it — some use only the numbers in front of them, some read what
another instruction did, repeat or invert it, undo it, change what a later
instruction will do, or cancel it. It must report the list after **every**
instruction, by reasoning alone. The truth is known exactly at every
stage, so a wrong answer shows where the model lost the state and on what
kind of instruction.

The formal definition — task, question set, scoring, reporting, limits —
is in **[BENCHMARK.md](BENCHMARK.md)**.

## The v1 question set

360 questions in [`benchmark/v1/questions.jsonl`](benchmark/v1/): 3 configs ×
10 / 20 / 40 / 80 instructions × lists of 10 / 20 / 40 numbers × 10 samples.
Each record holds the exact prompt, the true list after every instruction,
and analysis-only measures (never sent to a model) — among them the **chain
depth**, the number of instructions in the longest chain of references
(up to 11 in v1). [`manifest.json`](benchmark/v1/manifest.json) pins it with
a sha256.

## Use it

```bash
pip install .
```

**Score answers produced any way** — one `{id}.txt` per question, holding
the JSON stage log the prompt asks for:

```bash
depth-eval score path/to/answers          # writes results.json next to the folder
```

**Or run the reference solver** (Claude through the Anthropic API — the
prompt and two calculators, nothing else):

```bash
cp .env.example .env                       # add ANTHROPIC_API_KEY
depth-eval run --model claude-opus-5 --out runs/opus5
depth-eval score runs/opus5/answers
```

**Or run it through Claude Code** (no API key — the CLI's own login):

```bash
pip install '.[arena]'
depth-eval arena --model claude-haiku-4-5 --out runs/haiku-arena
```

The arena gives each question its own headless `claude -p` session in an
empty folder: the prompt as the only message, no system prompt, the two
calculators as the only tools, no settings, skills or memory. Each
session is audited from its transcript before its answer counts. The CLI
still adds one fixed note (~575 tokens: working folder, model name, date),
so arena results are labelled as such and never mixed with `run` results.

`run` and `arena` resume where they stopped and records every model turn and tool call
in `transcripts/`. `score` reports the exact rate, depth reached, and both
by config, instructions, list length and chain depth, plus a stage-by-stage
report for every answer.

**Reproduce the set** — `depth-eval verify` regenerates all 360 questions
from the code and requires identical bytes; `depth-eval build` writes them.

## What an instruction can be

Starting from `[4, 9, 2, 7]`, every result from the engine:

```
add 3                                              → [7, 12, 5, 10]
add the number at position 0 (the list now)       → [8, 13, 6, 11]
×10, then add how many numbers line 1 changed     → [44, 94, 24, 74]
add 5, then do the opposite of line 1             → [4, 9, 2, 7]
×3, then undo what line 1 did                     → [4, 9, 2, 7]
"from now on line 2 uses double" (+3 becomes +6)  → [10, 15, 8, 13]
only positions 1–2: ×10                           → [4, 90, 20, 7]
add position 0, twice over (re-read: +4, then +8) → [16, 21, 14, 19]
reverse                                           → [7, 2, 9, 4]
"hold until line k has executed"                  → runs right after line k
```

## Results

Preliminary, on earlier question sets (not v1), reasoning-only solvers:
Claude Fable 5.1 48 / 48, Claude Haiku 4.5 18 / 36 — the task separates
models. v1 results come from `depth-eval run` or `depth-eval arena`.

## Repository

```
benchmark/v1/        the question set + manifest
depth_eval/          the engine: operations, instructions, validation, generation
depth_eval/bench/    the benchmark: suite, grading, reference solver, arena, CLI
tests/               python -m pytest
```

## License and citation

Code: MIT ([LICENSE](LICENSE)). Question set: CC BY 4.0
([LICENSE-DATA](LICENSE-DATA)). Cite with [CITATION.cff](CITATION.cff).
Changes: [CHANGELOG.md](CHANGELOG.md).

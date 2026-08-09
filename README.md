# depth-eval

**How many chained instructions can a model hold in its head?**

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![SymPy](https://img.shields.io/badge/math-SymPy-green) ![Deterministic](https://img.shields.io/badge/runs-fully%20seeded-orange)

```
seeds ──► generator ──► question ──► solver ──► ground truth + trace
                          │
                          └──► the model gets the text. nothing else.
```

A list of numbers. A chain of instructions that mutate it — some waiting on
others, some reading the future, some rewriting each other. The model must
produce the final list by pure reasoning: no tools, no code. We know every
intermediate state, so a wrong answer tells us exactly *where* it fell off.

## What it does

- **Generate.** Seeded questions from weighted frequencies — operations,
  operand kinds, holds, meta verbs. Same seeds, same question, forever.
- **Solve.** Instructions form a dependency DAG (holds, effect references,
  edits). Static schedule, then exact symbolic replay — no floats, ever.
- **Validate.** Ten named error states (cycles, dead references, division
  by zero...) — a broken chain cannot become a question.
- **Trace.** Every event recorded: exact operation, resolved values, change
  counts, full state. Grading by divergence point comes free.

## Quick start

```bash
pip install sympy
```

```python
from depth_eval import generate, load_config

q = generate(list_seed=42, instruction_seed=37, steps=10, length=10,
             config=load_config("deep"))
print(q.text)    # the question a model would see
print(q.final)   # the answer we grade against
```

That's it. `steps` is depth, `length` is width — sweep both, get a
capability surface.

## The instruction space

```
data   :  15 ops  ×  7 operand kinds  ×  optional hold
           add, mod, gcd, min, ...       7, List[3], Start[p], B[k,p],
                                         Changed[j], p, ...
meta   :  mirror · negate · amplify · flip · rewrite · cancel · unwind
           read another instruction, edit its future, or undo its past
```

References resolve **at execution time** — "the number at position 3" means
position 3 *at that moment*, after everything before it already ran. Holds
and future references bend the timeline; frozen views (`Start`, companion
rows `B[k]`) remember what was.

## Difficulty as data

Question flavour lives in [configs/](configs/) as plain JSON — operand
frequencies, hold chance, meta verb mix. `shallow`, `default`, `deep`
ship; drop in your own state and it's selectable by name.

## Under the hood

```
depth_eval/
├── ops/           operations as SymPy expressions + reference resolution
├── meta/          the verb vocabulary (instructions about instructions)
├── dag.py         typed dependency edges, static scheduling
├── instructions.py  execution engine + event trace
├── validation.py  every error state, detected and named
└── generator.py   seeded question generation with repair
```

A run is identified by `(list_seed, instruction_seed, steps, length,
config, algorithm version)` — nothing else. Everything downstream is a pure
function of that tuple.

## Status

Research in progress: question engine complete and audited; grading harness
and benchmark runs next.

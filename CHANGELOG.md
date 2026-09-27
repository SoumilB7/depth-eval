# Changelog

The benchmark version pins the question set: `benchmark/v1/questions.jsonl`
changes only with a new version, and `depth-eval verify` proves a copy
matches the code that made it.

## 1.0.0 — first release

**The question set.** 360 questions, the full surface: 3 configs (shallow /
default / deep) × 10 / 20 / 40 / 80 instructions × lists of 10 / 20 / 40
numbers × 10 samples, every question on its own seed pair. Each record
carries the exact prompt, the true list after every instruction, and
analysis-only measures (chain depth, R, d, relative and held lines) that
are never sent to a model. `manifest.json` holds the sha256, the suite
definition, the config states and a canary GUID.

**The task.** Pure reasoning over a numbered chain of instructions that
change a list — direct lines, lines that read or change other lines,
holds, scopes, repeats, gates, ordered passes and moves. The answer is a
JSON stage log: the list after every instruction.

**Scoring.** Stage by stage against the truth: exact rate (every stage and
the final list right) is primary; depth reached (stages right before the
first error, as a share) and a per-stage report come with every grade.

**Tooling.** `depth-eval build | verify | run | arena | score`. `run` is
the reference API solver: the prompt and two calculators, nothing else,
with each model's own thinking settings and full output cap, so no answer
is cut short by the harness. `arena` runs each question in its own audited
headless Claude Code session with only the same two calculators (served
over MCP) — for runs without an API key, labelled separately.

**Pre-release audit.** Before any run, every line that repeats or undoes a
line which changes another instruction (rather than the list) was found
to read two ways; those lines now say exactly what they do. The set was
rebuilt and re-verified with that wording. The first pilot run found the
grader reading a reply whose chatter contained braces (`Touched = {3, 7}`)
as malformed; it now takes the first JSON object holding the stage log, as
the answer contract always said.

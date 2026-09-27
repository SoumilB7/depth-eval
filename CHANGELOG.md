# Changelog

The benchmark version pins the question set: `benchmark/v1/questions.jsonl`
changes only with a new version, and `depth-eval verify` proves a copy
matches the code that made it.

## 1.3.0 — the opening sentence

Same 360 questions and true answers. The prompt opened "Apply the
instructions by careful reasoning only" while every runner gives two
calculators — a model could read it as forbidding them (one pilot answer
used none). It now says: "Apply the instructions by careful reasoning and
report the list after every one; if you are given calculators, use them
for arithmetic only." Flagged 2026-09-26 as blocking before the first
run and missed until an outside review; fixed before any run on 1.2.0.

## 1.2.0 — second wording audit

Same 360 questions and true answers; the rules text changed in two
places, found by auditing every miss of the 1.1.0 pilots (Claude Haiku 4.5
15/36, Claude Sonnet 5 33/36):

- "positions instruction j applied to": a line that ran applied to its
  whole selection even where a value came out the same — only a skipped
  line applied to none. 1.1.0's "none for a line that did nothing" was
  read as covering a line that ran and changed nothing (one Haiku miss);
- "operand" is defined — the value a line combines with the number (the 1
  in "1 minus the number"), which is what "uses double its operand" and
  "uses x as its operand" change (one Haiku miss doubled the number).

Then every miss of both pilots was traced through the model's own path
(its text and every calculator call) by four independent reviewers,
which found three more places to pin down before any run on 1.2.0:

- for a move (sort, reverse, rotate, swap), "applied to" is every position
  that received a value from another position, even an equal value — and
  not one it left in place; the new "whole selection" sentence now
  excludes moves instead of contradicting them (a Sonnet miss counted a
  scoped sort's unmoved number);
- an operand given by a "from now on" line is read when the changed line
  runs, not when the "from now on" line does;
- "x minus the number" is its own inverse whatever x is (a number, a
  count, a value from a list).

Tooling (same day, no change to the set): every run folder carries
`run.json` (the set's name, version, sha256, the model, the runner); a
run never resumes against another set or model; `score` refuses answers
made on another set and records the set's identity in `results.json`; a
test fails as soon as the released prompts and the code's rules text
disagree.

## 1.1.0 — wording audit

Same 360 questions — the same starting lists, instructions and true
answers; only the rules text at the top of every prompt changed. A
36-question pilot (Claude Haiku 4.5, one per cell, on 1.0.0) and a scan of
all 360 questions against every rule the engine applies found five places
where the rules left a reading open. They now say:

- where a held line is logged: its one entry comes where it runs, never at
  its own number (334 questions have held lines; one pilot answer was
  right in every stage and failed on this alone);
- that "x minus the number" is its own inverse (an undo, inverse or flip
  of such a line: 295 lines across the set);
- that repeating or inverting a line runs the whole line — its selection,
  its "If" (checked again), its times over and its one-at-a-time order
  (and does nothing if that line is cancelled);
- that a line which did nothing applied to no positions, and an undo
  applied to the positions it put back;
- that a line run k times over is undone run by run, last run first, and
  that undoing an undo makes the change again.

Every clause is checked against the engine by a test. Results on 1.0.0
are not comparable with 1.1.0.

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

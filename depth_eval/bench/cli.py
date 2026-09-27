"""depth-eval — build the question set, run a model on it, score the answers.

    depth-eval build  [--out benchmark/v2]                write questions.jsonl + manifest.json
    depth-eval verify [--out benchmark/v2]                rebuild; the bytes must match
    depth-eval run    --model ID --out runs/NAME          the API solver on every question
    depth-eval arena  --model ID --out runs/NAME          the same through headless Claude Code
    depth-eval score  ANSWERS_DIR [--out results.json]    grade a directory of answers

`run` writes answers/{id}.txt and transcripts/{id}.jsonl (every model turn
and tool call) and resumes: a question with an answer file is skipped. A
failure on our side leaves no answer file. Every run folder carries
run.json — the set's name, version and sha256, the model and the runner —
and a run never resumes against a different set or model. `score` grades
any directory of {id}.txt stage logs — from `run` or from any other way of
asking a model — against questions.jsonl alone, refuses answers whose
run.json names another set, and writes the set's identity into
results.json; a missing answer is listed, never scored.
"""

import argparse
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .answer import MalformedAnswer, parse_stage_log
from .build import build, identity, load, verify
from .grade import grade

DEFAULT_SET = Path("benchmark/v2")


def _progress(n, total, qid):
    print(f"\r  {n}/{total}  {qid:<28}", end="", file=sys.stderr, flush=True)
    if n == total:
        print(file=sys.stderr)


def cmd_build(args) -> None:
    m = build(Path(args.out), _progress)
    print(f"built {m['questions']} questions -> {args.out}  sha256 {m['sha256'][:16]}…")


def cmd_verify(args) -> None:
    ok = verify(Path(args.out), _progress)
    print("verified: the rebuild matches byte for byte" if ok else "MISMATCH: the rebuild differs")
    sys.exit(0 if ok else 1)


def _stamp(out: Path, record: dict) -> None:
    """run.json: what this run folder was made against. A folder is never
    resumed against a different question set or model."""
    path = out / "run.json"
    if path.exists():
        earlier = json.loads(path.read_text())
        if (earlier["sha256"], earlier["model"]) != (record["sha256"], record["model"]):
            sys.exit(f"{out} holds a run of {earlier['model']} on {earlier['benchmark']} "
                     f"{earlier['version']} ({earlier['sha256'][:12]}…) — use a new --out")
        return
    path.write_text(json.dumps(record | {"started": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                               indent=2) + "\n")


def _run_all(args, solve_one, runner: str, model: str) -> None:
    """Every question not yet answered, `args.workers` at a time. solve_one(q)
    returns (answer or None, transcript events, summary). A question without
    an answer (our side failed) gets no answer file — never scored."""
    the_set = identity(Path(args.questions))
    prefixes = tuple((args.only or "").split(","))
    questions = [q for q in load(Path(args.questions) / "questions.jsonl") if q["id"].startswith(prefixes)]
    out = Path(args.out)
    (out / "answers").mkdir(parents=True, exist_ok=True)
    (out / "transcripts").mkdir(exist_ok=True)
    _stamp(out, the_set | {"model": model, "runner": runner})
    todo = [q for q in questions if not (out / "answers" / f"{q['id']}.txt").exists()]
    print(f"{len(todo)} to run ({len(questions) - len(todo)} already answered) — {runner} on {model}, "
          f"{the_set['benchmark']} {the_set['version']}")

    def one(q):
        try:
            answer, events, summary = solve_one(q)
        except Exception as e:  # our side failed: recorded, never scored
            answer, events, summary = None, [], {"outcome": f"not scored: {type(e).__name__}: {e}"}
        (out / "transcripts" / f"{q['id']}.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in events))
        if answer is not None:
            (out / "answers" / f"{q['id']}.txt").write_text(answer)
        return q["id"], summary

    with ThreadPoolExecutor(max_workers=args.workers) as pool, \
            (out / "log.jsonl").open("a") as log:
        for n, (qid, summary) in enumerate(pool.map(one, todo), start=1):
            log.write(json.dumps({"id": qid} | summary) + "\n")
            log.flush()
            print(f"  {n}/{len(todo)}  {qid:<28} {summary['outcome']}")


def cmd_run(args) -> None:
    from dotenv import load_dotenv

    from .solver import Solver

    load_dotenv()
    solver = Solver(model=args.model)

    def solve_one(q):
        events = []
        answer = solver.solve(q["prompt"], events.append)
        return answer, events, {"outcome": "answered",
                                "calculator_calls": sum("tool" in e for e in events)}

    _run_all(args, solve_one, "API solver", solver.model)


def cmd_arena(args) -> None:
    from . import arena

    _run_all(args, lambda q: arena.solve(q["prompt"], args.model), "arena (headless Claude Code)", args.model)


def calculator_numbers(transcript: Path) -> set[int]:
    """Every number a calculator returned in one answer's transcript (the API
    solver's or the arena's format); failed calls return none."""
    numbers = set()
    for line in transcript.read_text().splitlines():
        e = json.loads(line)
        outputs = [e["tool"]["output"]] if "tool" in e and not e["tool"]["is_error"] else []
        if e.get("type") == "user":
            for part in e["message"].get("content") or []:
                if isinstance(part, dict) and part.get("type") == "tool_result" and not part.get("is_error"):
                    c = part.get("content")
                    outputs.append(c if isinstance(c, str) else " ".join(x.get("text", "") for x in c or []))
        for out in outputs:
            numbers.update(int(x) for x in re.findall(r"-?\d+", out))
    return numbers


def calculated_share(stages, start, numbers) -> float | None:
    """The rules require every calculated number to come from a calculator.
    Of the numbers an answer newly wrote (not already in the list just before
    that stage), the share some calculator call returned; None if it wrote no
    new number. A coincidental match can only raise it."""
    prev, new, backed = start, 0, 0
    for stage in stages:
        pool = Counter(prev)
        for v in stage["state"]:
            if pool[v]:
                pool[v] -= 1
            else:
                new += 1
                backed += v in numbers
        prev = stage["state"]
    return round(backed / new, 3) if new else None


def _table(rows, key) -> dict:
    groups = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)
    return {str(k): {"n": len(v),
                     "exact": sum(r["exact"] for r in v),
                     "exact_rate": round(sum(r["exact"] for r in v) / len(v), 3),
                     "depth_reached": round(sum(r["stages_matched"] / r["stages_expected"]
                                                for r in v) / len(v), 3)}
            for k, v in sorted(groups.items())}


def _calculator_summary(rows) -> dict | None:
    shares = [r["from_calculator"] for r in rows if r["from_calculator"] is not None]
    if not shares:
        return None
    return {"answers_measured": len(shares), "mean_share": round(sum(shares) / len(shares), 3),
            "fully_from_calculator": sum(s == 1 for s in shares)}


def cmd_score(args) -> None:
    the_set = identity(Path(args.questions))
    questions = {q["id"]: q for q in load(Path(args.questions) / "questions.jsonl")}
    answers = Path(args.answers)
    stamp = answers.parent / "run.json"
    run = json.loads(stamp.read_text()) if stamp.exists() else None
    if run and run["sha256"] != the_set["sha256"]:
        sys.exit(f"these answers were made on {run['benchmark']} {run['version']} ({run['sha256'][:12]}…), "
                 f"not on {the_set['version']} ({the_set['sha256'][:12]}…) — score them against that set")
    rows, missing = [], []
    for qid, q in questions.items():
        path = answers / f"{qid}.txt"
        if not path.exists():
            missing.append(qid)
            continue
        g = grade(q["truth"]["stages"], q["truth"]["final"], path.read_text()).as_dict()
        share = None
        transcript = answers.parent / "transcripts" / f"{qid}.jsonl"
        if transcript.exists():
            try:
                start = json.loads(re.search(r"Starting list: (\[.*\])", q["prompt"]).group(1))
                share = calculated_share(parse_stage_log(path.read_text())["stages"], start,
                                         calculator_numbers(transcript))
            except MalformedAnswer:
                pass
        rows.append({"id": qid, "config": q["config"], "steps": q["steps"], "length": q["length"],
                     "chain_depth": q["measures"]["chain_depth"], "from_calculator": share} | g)
    if not rows:
        sys.exit(f"no answers in {answers}")
    summary = {
        "questions": the_set,
        "run": run,  # None: the answers carry no record of how they were made
        "answered": len(rows),
        "missing": missing,
        "exact": sum(r["exact"] for r in rows),
        "exact_rate": round(sum(r["exact"] for r in rows) / len(rows), 3),
        "depth_reached": round(sum(r["stages_matched"] / r["stages_expected"] for r in rows) / len(rows), 3),
        "by_config": _table(rows, lambda r: r["config"]),
        "by_steps": _table(rows, lambda r: r["steps"]),
        "by_length": _table(rows, lambda r: r["length"]),
        "by_chain_depth": _table(rows, lambda r: r["chain_depth"]),
        "from_calculator": _calculator_summary(rows),
    }
    out = Path(args.out) if args.out else answers.parent / "results.json"
    out.write_text(json.dumps({"summary": summary, "questions": rows}, indent=2) + "\n")
    print(f"{the_set['benchmark']} {the_set['version']}"
          + (f" — {run['model']}, {run['runner']}" if run else " — answers of unknown origin"))
    print(f"exact {summary['exact']}/{len(rows)} ({summary['exact_rate']:.1%})  "
          f"depth reached {summary['depth_reached']:.1%}  missing {len(missing)}  -> {out}")
    calc = summary["from_calculator"]
    if calc:
        print(f"  numbers from the calculator: {calc['mean_share']:.1%} on average; "
              f"{calc['fully_from_calculator']}/{calc['answers_measured']} answers entirely")
    for name in ("by_config", "by_steps", "by_length", "by_chain_depth"):
        print(f"  {name[3:]:<12} " + "  ".join(f"{k}: {v['exact']}/{v['n']}" for k, v in summary[name].items()))


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="depth-eval", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    for name, fn, text in (("build", cmd_build, "write the question set"),
                           ("verify", cmd_verify, "rebuild and compare byte for byte")):
        s = sub.add_parser(name, help=text)
        s.add_argument("--out", default=str(DEFAULT_SET))
        s.set_defaults(fn=fn)
    s = sub.add_parser("run", help="run the API solver on the question set")
    s.add_argument("--model", required=True)
    s.add_argument("--out", required=True, help="run directory (answers/, transcripts/)")
    s.add_argument("--questions", default=str(DEFAULT_SET))
    s.add_argument("--workers", type=int, default=8)
    s.add_argument("--only", help="run only ids starting with these (comma-separated), e.g. deep-s10")
    s.set_defaults(fn=cmd_run)
    s = sub.add_parser("arena", help="run through headless Claude Code (the CLI's login, no API key)")
    s.add_argument("--model", required=True)
    s.add_argument("--out", required=True, help="run directory (answers/, transcripts/, log.jsonl)")
    s.add_argument("--questions", default=str(DEFAULT_SET))
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--only", help="run only ids starting with these (comma-separated), e.g. deep-s10")
    s.set_defaults(fn=cmd_arena)
    s = sub.add_parser("score", help="grade a directory of {id}.txt answers")
    s.add_argument("answers")
    s.add_argument("--questions", default=str(DEFAULT_SET))
    s.add_argument("--out", help="results file (default: next to the answers directory)")
    s.set_defaults(fn=cmd_score)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()

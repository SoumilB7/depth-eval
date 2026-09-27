"""depth-eval — build the question set, run a model on it, score the answers.

    depth-eval build  [--out benchmark/v1]                write questions.jsonl + manifest.json
    depth-eval verify [--out benchmark/v1]                rebuild; the bytes must match
    depth-eval run    --model ID --out runs/NAME          the API solver on every question
    depth-eval arena  --model ID --out runs/NAME          the same through headless Claude Code
    depth-eval score  ANSWERS_DIR [--out results.json]    grade a directory of answers

`run` writes answers/{id}.txt and transcripts/{id}.jsonl (every model turn
and tool call) and resumes: a question with an answer file is skipped. A
failure on our side leaves no answer file. `score` grades any directory of
{id}.txt stage logs — from `run` or from any other way of asking a model —
against questions.jsonl alone; a missing answer is listed, never scored.
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .build import build, load, verify
from .grade import grade

DEFAULT_SET = Path("benchmark/v1")


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


def _run_all(args, solve_one, label: str) -> None:
    """Every question not yet answered, `args.workers` at a time. solve_one(q)
    returns (answer or None, transcript events, summary). A question without
    an answer (our side failed) gets no answer file — never scored."""
    prefixes = tuple((args.only or "").split(","))
    questions = [q for q in load(Path(args.questions) / "questions.jsonl") if q["id"].startswith(prefixes)]
    out = Path(args.out)
    (out / "answers").mkdir(parents=True, exist_ok=True)
    (out / "transcripts").mkdir(exist_ok=True)
    todo = [q for q in questions if not (out / "answers" / f"{q['id']}.txt").exists()]
    print(f"{len(todo)} to run ({len(questions) - len(todo)} already answered) — {label}")

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

    _run_all(args, solve_one, f"API solver on {solver.model}")


def cmd_arena(args) -> None:
    from . import arena

    _run_all(args, lambda q: arena.solve(q["prompt"], args.model),
             f"arena (headless Claude Code) on {args.model}")


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


def cmd_score(args) -> None:
    questions = {q["id"]: q for q in load(Path(args.questions) / "questions.jsonl")}
    answers = Path(args.answers)
    rows, missing = [], []
    for qid, q in questions.items():
        path = answers / f"{qid}.txt"
        if not path.exists():
            missing.append(qid)
            continue
        g = grade(q["truth"]["stages"], q["truth"]["final"], path.read_text()).as_dict()
        rows.append({"id": qid, "config": q["config"], "steps": q["steps"], "length": q["length"],
                     "chain_depth": q["measures"]["chain_depth"]} | g)
    if not rows:
        sys.exit(f"no answers in {answers}")
    summary = {
        "answered": len(rows),
        "missing": missing,
        "exact": sum(r["exact"] for r in rows),
        "exact_rate": round(sum(r["exact"] for r in rows) / len(rows), 3),
        "depth_reached": round(sum(r["stages_matched"] / r["stages_expected"] for r in rows) / len(rows), 3),
        "by_config": _table(rows, lambda r: r["config"]),
        "by_steps": _table(rows, lambda r: r["steps"]),
        "by_length": _table(rows, lambda r: r["length"]),
        "by_chain_depth": _table(rows, lambda r: r["chain_depth"]),
    }
    out = Path(args.out) if args.out else answers.parent / "results.json"
    out.write_text(json.dumps({"summary": summary, "questions": rows}, indent=2) + "\n")
    print(f"exact {summary['exact']}/{len(rows)} ({summary['exact_rate']:.1%})  "
          f"depth reached {summary['depth_reached']:.1%}  missing {len(missing)}  -> {out}")
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

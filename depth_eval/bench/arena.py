"""The arena — the benchmark run through a headless Claude Code call per
question, on the account the CLI is logged in with (no API key needed).

It recreates the API run (solver.py) as exactly as the CLI allows:

    question   the prompt, byte for byte, as the only user message (stdin)
    system     replaced with nothing        (--system-prompt "")
    tools      only the two calculators — calculator_server.py serves
               calculator.py's own names, descriptions and schemas
               (--tools "" turns every built-in tool off; --strict-mcp-config)
    context    no settings, skills, slash commands, plugins, project files
               or memory: an empty working folder per question
    answer     the final text, single-shot

What the CLI still injects, and cannot be turned off without an API key
(--bare): one fixed block of about 575 tokens — an environment note
(working folder, a scratchpad), the model's name, a token counter, the
account email and today's date. It is the same for every question and
carries nothing about any answer; results from here are labelled "arena"
and never mixed with API-run results.

Every question is audited from its own transcript before its answer
counts: the session's model, its tool list (exactly the two calculators),
no skills or slash commands, no plugin except the CLI's built-in ones, and
every tool call one of the two. Built-in plugins (telemetry, agents-md in
2.1.284) cannot be switched off — --safe-mode would drop the calculators
too — and add nothing the model sees: any tool, skill or command they
gave would fail the checks above, the working folder holds no AGENTS.md,
and the measured context is the same with and without them. The CLI
version is recorded with every question.
A question that fails the audit, or where the CLI itself fails, gets no
answer file — never scored, listed for a re-run.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import depth_eval

CALCULATORS = {"mcp__calc__calculator", "mcp__calc__bulk_calculator"}
TIMEOUT = 3600  # seconds per question


def command(model: str, mcp_config: Path) -> list[str]:
    return ["claude", "-p", "--model", model,
            "--system-prompt", "", "--tools", "",
            "--mcp-config", str(mcp_config), "--strict-mcp-config",
            "--allowedTools", ",".join(sorted(CALCULATORS)),
            "--setting-sources", "", "--disable-slash-commands",
            "--no-session-persistence", "--output-format", "stream-json", "--verbose"]


def _mcp_config(folder: Path) -> Path:
    path = folder / "mcp.json"
    root = str(Path(depth_eval.__file__).resolve().parent.parent)
    path.write_text(json.dumps({"mcpServers": {"calc": {
        "command": sys.executable, "args": ["-m", "depth_eval.bench.calculator_server"],
        "env": {"PYTHONPATH": root}}}}))
    return path


def audit(events: list[dict], model: str) -> str | None:
    """None when the session ran exactly as specified, else what was off."""
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
    if init is None:
        return "no session header"
    if init.get("model") != model:
        return f"ran on {init.get('model')}, not {model}"
    if set(init.get("tools") or []) != CALCULATORS:
        return f"tools were {init.get('tools')}"
    for key in ("skills", "slash_commands"):
        if init.get(key):
            return f"{key} were loaded: {init.get(key)}"
    foreign = [p.get("source") for p in init.get("plugins") or [] if not str(p.get("source")).endswith("@builtin")]
    if foreign:
        return f"plugins were loaded: {foreign}"
    for e in events:
        if e.get("type") == "assistant":
            for part in e["message"].get("content") or []:
                if part.get("type") == "tool_use" and part.get("name") not in CALCULATORS:
                    return f"called {part.get('name')}"
    return None


def solve(prompt: str, model: str) -> tuple[str | None, list[dict], dict]:
    """One question in its own empty folder. Returns (answer or None, the
    transcript events, a summary: outcome, turns, cost, tool calls)."""
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        cwd = folder / "arena"
        cwd.mkdir()
        run = subprocess.run(command(model, _mcp_config(folder)), input=prompt, text=True,
                             capture_output=True, cwd=cwd, timeout=TIMEOUT,
                             env={k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_SIMPLE")})
    events = [json.loads(line) for line in run.stdout.splitlines() if line.strip().startswith("{")]
    result = next((e for e in events if e.get("type") == "result"), {})
    init = next((e for e in events if e.get("subtype") == "init"), {})
    summary = {"cli": init.get("claude_code_version"),
               "turns": result.get("num_turns"), "cost_usd": result.get("total_cost_usd"),
               "calculator_calls": sum(1 for e in events if e.get("type") == "assistant"
                                       for p in e["message"].get("content") or []
                                       if p.get("type") == "tool_use")}
    problem = audit(events, model)
    if problem is None and (run.returncode != 0 or result.get("is_error") or "result" not in result):
        problem = f"the CLI failed: exit {run.returncode}, {result.get('subtype')} {run.stderr[-300:]!r}"
    summary["outcome"] = "answered" if problem is None else f"not scored: {problem}"
    return (result["result"] if problem is None else None), events, summary

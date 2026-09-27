"""Claude through the Anthropic API — the reference solver.

The integrity rule (eval-design.md, standing constraints; ruling
2026-09-26): the solver never executes anything and never reaches our code
or our answers. It gets the prompt as ONE user message and exactly two
tools — the calculator and the bulk calculator (calculator.py),
pure integer arithmetic. No system prompt, no files, no other tool.
`request()` builds every request in one place so a test can assert that.

The loop: send the conversation; while the model stops to call tools, run
them and append the results (append-only — the model's own turns go back
unchanged); the first reply that is not a tool call is the answer. Every
turn and every tool call is recorded, so a run's tool use is auditable.

Knobs (env, layered by .env — see .env.example):
    ANTHROPIC_API_KEY   required
    SOLVER_MODEL        default claude-opus-5
    SOLVER_EFFORT       low | medium | high | xhigh | max, default high
    SOLVER_MAX_TOKENS   default: the model's full output cap (streamed, so a
                        large cap costs nothing when unused) — an answer cut
                        short by OUR cap would not be the model's failure

The model under test stays the model under test: no server-side fallbacks,
never re-asked. A refusal, a max_tokens cut-off, or running past MAX_TURNS
is what the model produced (graded — usually malformed). An API error
after the SDK's own transport retries is OUR failure: it propagates, the
question gets no answer file, and scoring lists it as missing — never
scored, re-run with `depth-eval run` (it resumes).
"""

import logging
import os

import anthropic

from .calculator import TOOLS, CalculatorError

logger = logging.getLogger(__name__)


class Solver:
    """One question: the prompt, the calculators, text back. `record` gets
    every model turn and every tool call (the run's transcript)."""

    MAX_TURNS = 200  # model turns per question — a guard against a loop

    def __init__(self, model: str | None = None, client=None) -> None:
        self.client = client or anthropic.Anthropic()
        self.model = model or os.environ.get("SOLVER_MODEL", "claude-opus-5")
        self.effort = os.environ.get("SOLVER_EFFORT", "high")
        # Claude Haiku 4.5 predates adaptive thinking and effort: it takes a
        # fixed thinking budget below max_tokens and rejects `effort`; the
        # newer models (Opus 5 / 5.5, Sonnet 5, Fable 5.1) think adaptively
        self.legacy_thinking = self.model.startswith("claude-haiku-4-5")
        cap = 64000 if self.legacy_thinking else 128000
        self.max_tokens = int(os.environ.get("SOLVER_MAX_TOKENS", cap))

    def request(self, messages: list) -> dict:
        """The complete request: the conversation and the two calculators."""
        thinking = ({"thinking": {"type": "enabled", "budget_tokens": self.max_tokens - 16000}}
                    if self.legacy_thinking else
                    {"thinking": {"type": "adaptive"}, "output_config": {"effort": self.effort}})
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            **thinking,
            # client tools on a streamed request stream their input eagerly;
            # the calculator validates every input itself
            "tools": [tool.definition() | {"eager_input_streaming": True}
                      for tool in TOOLS.values()],
            "cache_control": {"type": "ephemeral"},  # the prefix repeats every turn
            "messages": messages,
        }

    def solve(self, prompt: str, record=lambda event: None) -> str:
        messages = [{"role": "user", "content": prompt}]
        for turn in range(1, self.MAX_TURNS + 1):
            with self.client.messages.stream(**self.request(messages)) as stream:
                message = stream.get_final_message()
            record({"call": {
                "turn": turn,
                "model": message.model,
                "stop_reason": message.stop_reason,
                "stop_details": (message.stop_details.category
                                 if message.stop_reason == "refusal" and message.stop_details
                                 else None),
                "usage": {"input": message.usage.input_tokens,
                          "output": message.usage.output_tokens},
            }})
            if message.stop_reason != "tool_use":
                break
            messages.append({"role": "assistant", "content": message.content})
            messages.append({"role": "user", "content": [
                self.use_tool(block, record) for block in message.content if block.type == "tool_use"
            ]})
        else:
            logger.warning(f"no answer within {self.MAX_TURNS} turns")
            return ""
        if message.stop_reason == "refusal":
            logger.warning("the model refused")
            return ""
        return "".join(block.text for block in message.content if block.type == "text")

    def use_tool(self, block, record) -> dict:
        """Run one tool call; the result block goes back to the model."""
        tool = TOOLS.get(block.name)
        try:
            if tool is None:
                raise CalculatorError(f"unknown tool {block.name!r}")
            output, is_error = tool.run(block.input), False
        except CalculatorError as e:
            output, is_error = f"Error: {e}", True
        record({"tool": {"name": block.name, "input": block.input,
                              "output": output, "is_error": is_error}})
        return {"type": "tool_result", "tool_use_id": block.id,
                "content": output, "is_error": is_error}

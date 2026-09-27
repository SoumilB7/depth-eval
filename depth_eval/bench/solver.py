"""Claude through the Anthropic API — the benchmark solver.

The integrity rule (eval-design.md, standing constraints; ruling
2026-09-26): the solver never executes anything and never reaches our code
or our answers. It gets the prompt as ONE user message and exactly two
tools — the calculator and the bulk calculator (harness/calculator.py),
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
    SOLVER_MAX_TOKENS   default 64000 per turn (streamed, so a large cap
                        costs nothing when unused)

The model under test stays the model under test: no server-side fallbacks,
never re-asked. A refusal, a max_tokens cut-off, or running past MAX_TURNS
is what the model produced (graded — usually malformed). An API error
after the SDK's own transport retries is OUR failure: it propagates and
the run ends as `error` (agent.py), unscored.
"""

import logging
import os

import anthropic

from ..agent import Agent
from ..calculator import TOOLS, CalculatorError

logger = logging.getLogger()


class Claude(Agent):
    """One question: the prompt, the calculators, text back."""

    MAX_TURNS = 200  # model turns per question — a guard against a loop

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.client = anthropic.Anthropic()
        self.model = os.environ.get("SOLVER_MODEL", "claude-opus-5")
        self.effort = os.environ.get("SOLVER_EFFORT", "high")
        self.max_tokens = int(os.environ.get("SOLVER_MAX_TOKENS", "64000"))

    def request(self, messages: list) -> dict:
        """The complete request: the conversation and the two calculators."""
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
            # client tools on a streamed request stream their input eagerly;
            # the calculator validates every input itself
            "tools": [tool.definition() | {"eager_input_streaming": True}
                      for tool in TOOLS.values()],
            "cache_control": {"type": "ephemeral"},  # the prefix repeats every turn
            "messages": messages,
        }

    def solve(self, observation: dict) -> str:
        messages = [{"role": "user", "content": observation["prompt"]}]
        for turn in range(1, self.MAX_TURNS + 1):
            with self.client.messages.stream(**self.request(messages)) as stream:
                message = stream.get_final_message()
            self.record({"call": {
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
                self.use_tool(block) for block in message.content if block.type == "tool_use"
            ]})
        else:
            logger.warning(f"{self.env.spec}: no answer within {self.MAX_TURNS} turns")
            return ""
        if message.stop_reason == "refusal":
            logger.warning(f"{self.env.spec}: the model refused")
            return ""
        return "".join(block.text for block in message.content if block.type == "text")

    def use_tool(self, block) -> dict:
        """Run one tool call; the result block goes back to the model."""
        tool = TOOLS.get(block.name)
        try:
            if tool is None:
                raise CalculatorError(f"unknown tool {block.name!r}")
            output, is_error = tool.run(block.input), False
        except CalculatorError as e:
            output, is_error = f"Error: {e}", True
        self.record({"tool": {"name": block.name, "input": block.input,
                              "output": output, "is_error": is_error}})
        return {"type": "tool_result", "tool_use_id": block.id,
                "content": output, "is_error": is_error}

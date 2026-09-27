"""The answer contract — one JSON stage log, exactly as the prompt asks:

    {"stages": [{"ran": <instruction number>, "state": [<the whole list>]}, ...],
     "final": [<the final list>]}

The shape is fixed by the engine's CONVENTIONS (depth_eval/lines.py); this
module only checks a reply against it. parse_stage_log accepts the object
itself or the raw text of a model reply (the first JSON object in it, code
fences and chatter tolerated) and returns the normalized dict, or raises
MalformedAnswer saying what is wrong. What to DO about a malformed reply
(retry, score it, bucket it) is the agent's policy — still an open
decision (harness-study.md); the environment just grades it as diverging
before stage 1.
"""

import json


class MalformedAnswer(ValueError):
    """The reply is not a stage log of the contract's shape."""


def _load(text: str | bytes):
    text = text.decode() if isinstance(text, bytes) else text
    for candidate in (text.strip(), text[text.find("{"): text.rfind("}") + 1]):
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    raise MalformedAnswer("no JSON object found in the answer")


def _int(value, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MalformedAnswer(f"{what} must be an integer, got {value!r}")
    return value


def _ints(values, what: str) -> list[int]:
    if not isinstance(values, list):
        raise MalformedAnswer(f"{what} must be a list of integers")
    return [_int(v, f"{what}[{i}]") for i, v in enumerate(values)]


def parse_stage_log(answer) -> dict:
    """Normalize a reply (object or text) to {"stages": [...], "final": [...]}."""
    obj = _load(answer) if isinstance(answer, (str, bytes)) else answer
    if not isinstance(obj, dict):
        raise MalformedAnswer("answer is not a JSON object")
    stages = obj.get("stages")
    if not isinstance(stages, list):
        raise MalformedAnswer('"stages" must be a list')
    parsed = []
    for i, stage in enumerate(stages, start=1):
        if not isinstance(stage, dict) or "ran" not in stage or "state" not in stage:
            raise MalformedAnswer(f'stage {i} must be an object with "ran" and "state"')
        parsed.append(
            {
                "ran": _int(stage["ran"], f"stage {i} ran"),
                "state": _ints(stage["state"], f"stage {i} state"),
            }
        )
    return {"stages": parsed, "final": _ints(obj.get("final"), '"final"')}

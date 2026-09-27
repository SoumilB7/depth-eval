"""The answer contract — one JSON stage log, exactly as the prompt asks:

    {"stages": [{"ran": <instruction number>, "state": [<the whole list>]}, ...],
     "final": [<the final list>]}

The shape is fixed by the engine's CONVENTIONS (depth_eval/lines.py); this
module only checks a reply against it. parse_stage_log accepts the object
itself or the raw text of a model reply (the first JSON object in it, code
fences and chatter tolerated) and returns the normalized dict, or raises
MalformedAnswer saying what is wrong. A malformed reply is the model's
answer: single-shot, never retried, graded as diverging before stage 1.
"""

import json


class MalformedAnswer(ValueError):
    """The reply is not a stage log of the contract's shape."""


def _load(text: str | bytes):
    """The whole reply as JSON, else the first object in it holding "stages"
    (chatter may itself contain braces, e.g. "Touched = {3, 7}"), else the
    first JSON object in it."""
    text = text.decode() if isinstance(text, bytes) else text
    try:
        return json.loads(text.strip())
    except ValueError:
        pass
    decoder, first = json.JSONDecoder(), None
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj = decoder.raw_decode(text, i)[0]
        except ValueError:
            continue
        if isinstance(obj, dict) and "stages" in obj:
            return obj
        first = obj if first is None else first
    if first is not None:
        return first
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

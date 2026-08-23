"""Meta instructions — instructions about other instructions.

Two types live here (classes differentiate kinds, members are instances):

- MetaVerb: one KIND of manipulation. Its `klass` declares what it needs
  from its target — the standing rule made into a type field. Nothing
  here moves a line in time (only holds do, dag.py):
    "read" -> def  j→i : i reads j's current definition; j need not have run
    "edit" -> def  j→i : i reads the listed text and changes j's definition;
              j must still be AHEAD in the schedule (dead_edit otherwise).
              Edits mutate definitions, NEVER the listing, never the past.
    "undo" -> result   : i needs j's actual execution record, so j must have
              run by i's turn — listed earlier, or i holds until j
              (unexecuted_reference otherwise).
  Its `transform` IS its meaning (meta/verbs.py): given the target's
  current definition, the meta line and its number, it returns the
  definition to run (read verbs) or the target's new definition (edit
  verbs, None = cancelled). Undo verbs replay the execution record instead
  and carry no transform.

- MetaInstruction: one line of a question — a verb aimed at a target
  instruction number, with an optional operand (rewrite needs one) and the
  same hold mechanics as data instructions. An operand written on this
  line may read B — this line's own private list.
"""

from dataclasses import dataclass
from typing import Callable

from ..ops.operands import phrase as operand_phrase
from ..ops.operands import uses_companion


@dataclass(frozen=True)
class MetaVerb:
    name: str
    klass: str  # "read" | "edit" | "undo"
    phrase: str  # sentence template; {j} = target number, {x} = operand
    takes_operand: bool = False
    transform: Callable | None = None  # (definition, meta line, number) -> definition | None


@dataclass(frozen=True)
class MetaInstruction:
    verb: MetaVerb
    target: int
    operand: object | None = None
    hold_until_after: int | None = None

    def render(self, number: int, companion: list[int] | None = None) -> str:
        x = operand_phrase(self.operand) if self.operand is not None else ""
        body = self.verb.phrase.format(j=self.target, x=x)
        if (
            companion is not None
            and self.operand is not None
            and uses_companion(self.operand)
        ):
            body = f"{body} — this instruction's list B = {list(companion)}"
        if self.hold_until_after is not None:
            return (
                f"{number}. Hold this instruction until instruction "
                f"{self.hold_until_after} has executed, then apply it immediately after it: {body}"
            )
        return f"{number}. {body}"

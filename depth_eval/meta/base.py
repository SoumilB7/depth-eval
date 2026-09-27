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

    def changes_an_instruction(self, chain: list, j: int) -> bool:
        """Does line j, followed through repeat/invert lines, end at a
        "from now on" line — a line that changes another instruction, not
        the list?"""
        seen = set()
        while isinstance(chain[j - 1], MetaInstruction) and chain[j - 1].verb.klass == "read":
            if j in seen:
                return False
            seen.add(j)
            j = chain[j - 1].target
        line = chain[j - 1]
        return isinstance(line, MetaInstruction) and line.verb.klass == "edit"

    def render(self, number: int, companion: list[int] | None = None,
               chain: list | None = None) -> str:
        """chain: the whole question, so a repeat or an undo aimed at a line
        that changes an instruction (not the list) says exactly what that
        means — without naming where the chain ends (following it is the
        task). Ruled 2026-09-29: the text says it."""
        x = operand_phrase(self.operand) if self.operand is not None else ""
        body = self.verb.phrase.format(j=self.target, x=x)
        if chain is not None and self.verb.name in ("mirror", "unwind") \
                and self.changes_an_instruction(chain, self.target):
            body = (f"Do again what instruction {self.target} does, as it is currently defined: "
                    "it changes another instruction rather than the list, so make that change "
                    "once more (if it is cancelled, do nothing)"
                    if self.verb.name == "mirror" else
                    f"Undo what instruction {self.target} actually did: it changed no numbers "
                    "(it changes another instruction rather than the list), so this does nothing")
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

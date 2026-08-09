"""Meta instructions — instructions about other instructions.

Two types live here (classes differentiate kinds, members are instances):

- MetaVerb: one KIND of manipulation. Its `klass` declares the DAG edges it
  creates — the standing rule made into a type field:
    "read" -> def  j→i : i reads j's current definition; timeline untouched
    "edit" -> exec i⇒j : the TARGET parks until its editor has run (its
              definition isn't final before that) + def j→i (editor reads
              the listed text). Edits mutate definitions, NEVER the listing,
              and never retroactively — reordering makes that impossible.
    "undo" -> exec j⇒i : i needs j's actual execution record (the trace).

- MetaInstruction: one line of a question — a verb aimed at a target
  instruction number, with an optional operand (rewrite needs one) and the
  same hold mechanics as data instructions.
"""

from dataclasses import dataclass

from ..ops.operands import phrase as operand_phrase


@dataclass(frozen=True)
class MetaVerb:
    name: str
    klass: str  # "read" | "edit" | "undo"
    phrase: str  # sentence template; {j} = target number, {x} = operand
    takes_operand: bool = False


@dataclass(frozen=True)
class MetaInstruction:
    verb: MetaVerb
    target: int
    operand: object | None = None
    hold_until_after: int | None = None

    def render(self, number: int) -> str:
        x = operand_phrase(self.operand) if self.operand is not None else ""
        body = self.verb.phrase.format(j=self.target, x=x)
        if self.hold_until_after is not None:
            return (
                f"{number}. Hold this instruction until instruction "
                f"{self.hold_until_after} has executed, then apply it: {body}"
            )
        return f"{number}. {body}"

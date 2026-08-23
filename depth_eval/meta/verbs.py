"""The meta-verb vocabulary. Each verb is a MetaVerb instance whose
`transform` IS its meaning — the executor runs them generically.

    read verbs   transform(definition, line, number) -> definition to RUN
      mirror j   j's current definition, as is (operand re-resolved now)
      negate j   j's current definition inverted (invertible only)
    edit verbs   transform(definition, line, number) -> j's NEW definition
      amplify j  operand doubled                  (map lines only)
      flip j     op / move inverted               (invertible only)
      rewrite j  operand := this line's operand,  (map lines only;
                 its B is this line's list)
      cancel j   None — j becomes a no-op event (Changed[j] = 0)
    undo verb    no transform: replays j's execution record in reverse
      unwind j

A cancelled target (definition None) is never transformed: cancel wins.
Edits compose in execution order; Changed[editor] = 0.
"""

from ..definitions import MapDef
from .base import MetaVerb


def _inverted(definition, verb: str):
    inverted = definition.inverted()
    if inverted is None:
        raise ValueError(f"cannot {verb} {definition.name} — it has no inverse")
    return inverted


def _map_only(definition, verb: str) -> MapDef:
    if not isinstance(definition, MapDef):
        raise ValueError(f"cannot {verb} a move — it has no operand")
    return definition


META_VERBS: dict[str, MetaVerb] = {
    v.name: v
    for v in [
        MetaVerb(
            "mirror", "read",
            "Apply instruction {j}'s operation (as it is currently defined) to the "
            "list now, as one more run of it",
            transform=lambda d, line, n: d,
        ),
        MetaVerb(
            "negate", "read",
            "Apply the inverse of instruction {j}'s operation (as it is currently "
            "defined) to the list now",
            transform=lambda d, line, n: _inverted(d, "negate"),
        ),
        MetaVerb(
            "amplify", "edit",
            "From now on, instruction {j} uses double its operand",
            transform=lambda d, line, n: _map_only(d, "amplify").amplified(),
        ),
        MetaVerb(
            "flip", "edit",
            "From now on, instruction {j} does the inverse of its operation",
            transform=lambda d, line, n: _inverted(d, "flip"),
        ),
        MetaVerb(
            "rewrite", "edit",
            "From now on, instruction {j} uses {x} as its operand",
            takes_operand=True,
            transform=lambda d, line, n: _map_only(d, "rewrite").rewritten(line.operand, n),
        ),
        MetaVerb(
            "cancel", "edit",
            "From now on, instruction {j} is cancelled: it does nothing when it runs",
            transform=lambda d, line, n: None,
        ),
        MetaVerb(
            "unwind", "undo",
            "Undo what instruction {j} actually did: apply the inverse of its "
            "operation, with the same values it used, at the same positions, to "
            "the list as it is now",
        ),
    ]
}

"""Swarm — many agents over many run specs, the ARC-AGI orchestration.

Lifecycle, kept exactly as theirs: open a scorecard -> one agent per spec,
one daemon thread each -> join all -> every run reports its score -> close
the scorecard (writes the JSON report). main.py additionally closes the
card on SIGINT so an interrupted sweep still yields a partial report.
"""

import logging
from threading import Thread
from typing import Optional

from . import env
from .agent import Agent, Playback
from .recorder import RECORDING_SUFFIX, Recorder
from .scorecard import RunScore, Scorecard

logger = logging.getLogger()


class Swarm:
    """Orchestration for one agent class playing many run specs."""

    def __init__(
        self,
        agent: str,
        specs: list[str],
        tags: Optional[list[str]] = None,
    ) -> None:
        from . import AVAILABLE_AGENTS  # here to avoid a circular import

        self.agent_name = agent
        if agent.endswith(RECORDING_SUFFIX):
            self.agent_class: type[Agent] = Playback
            self.specs = [Recorder.get_spec(agent)]
            base_tags = ["playback", Recorder.get_guid(agent)]
        else:
            self.agent_class = AVAILABLE_AGENTS[agent]
            self.specs = specs
            base_tags = ["agent", agent]
        self.tags = base_tags + (tags or [])
        self.agents: list[Agent] = []
        self.scorecard: Optional[Scorecard] = None

    def main(self) -> Optional[dict]:
        """Run every spec to completion, then close and return the report."""
        self.scorecard = Scorecard(tags=self.tags)
        logger.info(f"opened scorecard {self.scorecard.card_id}")

        for spec in self.specs:
            self.agents.append(
                self.agent_class(
                    card_id=self.scorecard.card_id,
                    env=env.make(spec),
                    agent_name=self.agent_name,
                    tags=self.tags,
                )
            )

        threads = [Thread(target=a.main, daemon=True) for a in self.agents]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        return self.close_scorecard()

    def close_scorecard(self) -> Optional[dict]:
        """Collect finished runs and write the report. Safe to call once —
        from the normal path or from the SIGINT handler, whichever fires."""
        card, self.scorecard = self.scorecard, None
        if card is None:
            return None
        for a in self.agents:
            if a.result is not None:
                card.add(
                    RunScore(
                        spec=str(a.env.spec),
                        agent=a.agent_name,
                        attempts=len(a.attempts),
                        exact=a.result.exact,
                        first_wrong=a.result.first_wrong,
                        seconds=a.seconds,
                    )
                )
        report = card.close()
        logger.info(
            f"scorecard {report['card_id']}: {report['solved']}/{report['played']} "
            f"solved -> {report['path']}"
        )
        return report

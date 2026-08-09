# ruff: noqa: E402
"""CLI entry — the ARC-AGI main.py ground rules, without the online parts.

Kept exactly: dotenv layering (.env.example defaults, .env overrides),
--agent/--tags argparse shape, recording filenames as agents, and the
SIGINT handler that still closes the scorecard so Ctrl+C yields a partial
report. Dropped: the games API fetch — specs are local and explicit.
"""

from dotenv import load_dotenv

load_dotenv(dotenv_path=".env.example")
load_dotenv(dotenv_path=".env", override=True)

import argparse
import logging
import os
import signal
import sys
from functools import partial
from types import FrameType
from typing import Optional

from harness import AVAILABLE_AGENTS, Swarm
from harness.recorder import RECORDING_SUFFIX

logger = logging.getLogger()


def cleanup(swarm: Swarm, signum: Optional[int], frame: Optional[FrameType]) -> None:
    logger.info("received SIGINT, closing scorecard...")
    swarm.close_scorecard()
    sys.exit(0)


def main() -> None:
    log_level = logging.DEBUG if os.environ.get("DEBUG") == "True" else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        stream=sys.stdout,
    )

    parser = argparse.ArgumentParser(description="depth-eval harness")
    parser.add_argument(
        "-a",
        "--agent",
        required=True,
        help=(
            "agent to run: one of "
            f"{sorted(AVAILABLE_AGENTS)} or a *{RECORDING_SUFFIX} filename "
            "to replay"
        ),
    )
    parser.add_argument(
        "-s",
        "--spec",
        help=(
            "comma-separated run specs, e.g. "
            "default-s10-L10-ls42-is37,deep-s20-L10-ls1-is11 "
            "(not needed for playback)"
        ),
    )
    parser.add_argument(
        "-t",
        "--tags",
        help="comma-separated scorecard tags (e.g. 'experiment,v1')",
    )
    args = parser.parse_args()

    is_playback = args.agent.endswith(RECORDING_SUFFIX)
    if not is_playback and args.agent not in AVAILABLE_AGENTS:
        logger.error(f"unknown agent {args.agent!r} — choose from {sorted(AVAILABLE_AGENTS)}")
        return
    specs = [s.strip() for s in args.spec.split(",")] if args.spec else []
    if not specs and not is_playback:
        logger.error("at least one --spec is required (playback derives its own)")
        return
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else []

    swarm = Swarm(args.agent, specs, tags=tags)
    signal.signal(signal.SIGINT, partial(cleanup, swarm))
    swarm.main()


if __name__ == "__main__":
    main()

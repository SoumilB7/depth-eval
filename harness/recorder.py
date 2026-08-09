"""Append-only JSONL recording of runs — the ARC-AGI recorder, minimal.

Every event is one line: {"timestamp": ..., "data": {...}}. Filenames are
self-describing and parseable:

    {spec}.{agent}.{guid}.recording.jsonl

The filename IS an agent name: passing it as --agent replays the recorded
answers through Playback (see agent.py) — re-grading without re-running a
model. That round-trip is the whole reason this file exists.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

RECORDING_SUFFIX = ".recording.jsonl"


def get_recordings_dir() -> str:
    """Current recordings directory (env var wins, like every knob here)."""
    return os.environ.get("RECORDINGS_DIR", "recordings")


class Recorder:
    def __init__(self, prefix: str, filename: Optional[str] = None) -> None:
        self.guid = self.get_guid(filename) if filename else str(uuid.uuid4())
        self.prefix = prefix
        recordings_dir = get_recordings_dir()
        self.filename = os.path.join(
            recordings_dir,
            filename if filename else f"{self.prefix}.{self.guid}{RECORDING_SUFFIX}",
        )
        os.makedirs(recordings_dir, exist_ok=True)

    def record(self, data: dict[str, Any]) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        with open(self.filename, "a", encoding="utf-8") as f:
            json.dump(event, f)
            f.write("\n")

    def get(self) -> list[dict[str, Any]]:
        if not os.path.isfile(self.filename):
            return []
        with open(self.filename, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def __repr__(self) -> str:
        return f"<Recorder guid={self.guid} file={self.filename}>"

    @classmethod
    def list(cls) -> list[str]:
        recordings_dir = get_recordings_dir()
        if not os.path.isdir(recordings_dir):
            return []
        return [f for f in os.listdir(recordings_dir) if f.endswith(RECORDING_SUFFIX)]

    @classmethod
    def get_prefix(cls, filename: str) -> str:
        """spec.agent.guid.recording.jsonl -> spec.agent"""
        return ".".join(filename.split(".")[:-3]) if "." in filename else filename

    @classmethod
    def get_spec(cls, filename: str) -> str:
        """spec.agent.guid.recording.jsonl -> spec"""
        return filename.split(".")[0]

    @classmethod
    def get_guid(cls, filename: str) -> str:
        """spec.agent.guid.recording.jsonl -> guid"""
        return filename.split(".")[-3] if "." in filename else filename

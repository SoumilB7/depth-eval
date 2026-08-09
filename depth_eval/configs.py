"""Named generator configs, stored as openly editable JSON.

Each file in the top-level `configs/` directory is one selectable state —
`configs/deep.json` is loaded as load_config("deep"). Field names in the
JSON mirror GeneratorConfig exactly; unknown keys are an error so a typo
can't silently fall back to a default.

The chosen config is part of a run's identity: (list_seed,
instruction_seed, config, algorithm version) -> question. Editing a JSON
therefore changes every question generated under that name — treat the
files as versioned states, not scratch.
"""

import json
from pathlib import Path

from .generator import GeneratorConfig

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"

_FIELDS = set(GeneratorConfig.__dataclass_fields__)


def list_configs(directory: Path | None = None) -> list[str]:
    directory = directory or CONFIG_DIR
    return sorted(p.stem for p in directory.glob("*.json"))


def load_config(name: str = "default", directory: Path | None = None) -> GeneratorConfig:
    directory = directory or CONFIG_DIR
    path = directory / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"no config named {name!r} — available: {list_configs(directory)}"
        )
    data = json.loads(path.read_text())
    unknown = set(data) - _FIELDS
    if unknown:
        raise ValueError(f"unknown keys in {path.name}: {sorted(unknown)}")
    return GeneratorConfig(**data)

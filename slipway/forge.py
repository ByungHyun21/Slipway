"""Forge project layout: discovery, initialization, paths."""

from __future__ import annotations

import time
from pathlib import Path

import yaml

MARKER = "forge.yaml"

DIRS = [
    "canon/story",
    "canon/characters",
    "canon/style",
    "assets",
    "staging",
    "gates",
    "approved",
    "previews",
    "exports",
]

DEFAULT_GATE_CONFIG = {
    "checksum": True,
    "provenance": True,
    "image": {
        "formats": ["png", "jpg", "jpeg", "webp", "gif"],
        "min_width": 16,
        "min_height": 16,
        "max_width": 8192,
        "max_height": 8192,
    },
    "sprite": {"requires_alpha": True},
    "video": {"formats": ["mp4", "webm", "mov"]},
    "mesh": {"formats": ["glb", "gltf", "obj", "fbx", "usdz"]},
    "text": {"formats": ["md", "txt"], "min_chars": 1},
    "audio": {
        "formats": ["wav"],
        "min_duration": 0.1,
        "max_duration": 300.0,
        "max_clip_ratio": 0.0,
        "min_rms": 0.0005,
        "max_rms": 0.99,
    },
}


def find(start: Path | str = ".") -> Path | None:
    """Walk up from *start* looking for a forge root."""
    cur = Path(start).resolve()
    for base in [cur, *cur.parents]:
        if (base / MARKER).is_file():
            return base
    return None


def require(start: Path | str = ".") -> Path:
    root = find(start)
    if root is None:
        raise SystemExit("error: not inside a forge (run `slip init` first)")
    return root


def init(path: Path | str = ".") -> Path:
    """Create a forge at *path*. Idempotent; never clobbers existing files."""
    root = Path(path).resolve()
    marker = root / MARKER
    if marker.exists():
        return root
    root.mkdir(parents=True, exist_ok=True)
    for d in DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    marker.write_text(
        yaml.dump(
            {
                "name": root.name,
                "layout": 1,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            sort_keys=False,
        )
    )
    gate_cfg = root / "gates" / "config.yaml"
    if not gate_cfg.exists():
        gate_cfg.write_text(
            "# Deterministic gate configuration. Merged over built-in defaults.\n"
            + yaml.dump(DEFAULT_GATE_CONFIG, sort_keys=False)
        )
    for keep in ("staging", "approved", "previews", "exports"):
        gitkeep = root / keep / ".gitkeep"
        if not any(p for p in (root / keep).iterdir()):
            gitkeep.touch()
    return root

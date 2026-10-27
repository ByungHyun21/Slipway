"""Derived preview assets (video posters etc.), generated at approval time.

Originals in staging/approved are never touched; derivations live under
previews/<id>/<rev>/ and exist only for approved revisions, so serving them
cannot leak unapproved work.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import store

VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".avi"}


def poster_path(root: Path, asset_id: str, rev: int, stem: str) -> Path:
    return root / "previews" / asset_id / str(rev) / f"{stem}.poster.jpg"


def derive(root: Path, asset_id: str, rev: int, files: list[dict]) -> list[Path]:
    """Generate poster JPEGs for approved video files. Best-effort: missing
    ffmpeg or a failed transcode never blocks approval."""
    src_dir = store.approved_dir(root, asset_id, rev)
    made = []
    for f in files:
        p = src_dir / f["name"]
        if p.suffix.lower() not in VIDEO_EXT:
            continue
        dst = poster_path(root, asset_id, rev, p.stem)
        if dst.exists():
            made.append(dst)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                ["ffmpeg", "-loglevel", "error", "-y", "-ss", "0.1", "-i", str(p),
                 "-frames:v", "1", "-vf", "scale=480:-2", str(dst)],
                check=True, timeout=120)
            made.append(dst)
        except Exception:
            dst.unlink(missing_ok=True)
    return made

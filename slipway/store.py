"""Checksums and staging/approved/export file handling."""

from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return f"sha256:{h.hexdigest()}"


def verify(path: Path, checksum: str) -> bool:
    return sha256_file(path) == checksum


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def staging_dir(root: Path, asset_id: str, rev: int) -> Path:
    return root / "staging" / asset_id / str(rev)


def approved_dir(root: Path, asset_id: str, rev: int) -> Path:
    return root / "approved" / asset_id / str(rev)


def ingest(root: Path, asset_id: str, rev: int, sources: list[Path]) -> list[dict]:
    """Copy raw generations into staging/<id>/<rev>/, record checksums."""
    dest = staging_dir(root, asset_id, rev)
    dest.mkdir(parents=True, exist_ok=False)
    files = []
    for src in sources:
        if not src.is_file():
            raise SystemExit(f"error: no such file: {src}")
        shutil.copy2(src, dest / src.name)
        stored = dest / src.name
        files.append({"name": src.name, "checksum": sha256_file(stored),
                      "bytes": stored.stat().st_size})
    return files


def approve_copy(root: Path, asset_id: str, rev: int, files: list[dict]) -> Path:
    """Copy a gated revision into approved/<id>/<rev>/, verifying checksums."""
    src_dir, dst_dir = staging_dir(root, asset_id, rev), approved_dir(root, asset_id, rev)
    if dst_dir.exists():
        raise SystemExit(f"error: revision {rev} of {asset_id!r} is already approved")
    dst_dir.mkdir(parents=True)
    for f in files:
        src = src_dir / f["name"]
        if not src.is_file():
            raise SystemExit(f"error: staged file missing: {src}")
        if not verify(src, f["checksum"]):
            raise SystemExit(f"error: checksum mismatch for {src}; refusing to approve")
        shutil.copy2(src, dst_dir / f["name"])
    return dst_dir


def export_copy(root: Path, asset_id: str, rev: int, files: list[dict],
                target: Path) -> Path:
    """Copy approved files to an external target dir (the launch)."""
    src_dir = approved_dir(root, asset_id, rev)
    dst_dir = target / asset_id / str(rev)
    dst_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        src = src_dir / f["name"]
        if not src.is_file():
            raise SystemExit(f"error: approved file missing: {src}")
        if not verify(src, f["checksum"]):
            raise SystemExit(f"error: checksum mismatch for {src}; refusing to export")
        shutil.copy2(src, dst_dir / f["name"])
    return dst_dir

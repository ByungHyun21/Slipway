"""Asset registry: one YAML file per asset under assets/<id>.yaml."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from . import state

TYPES = ["story", "image", "sprite", "video", "music", "sfx", "voice", "mesh"]

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class RegistryError(Exception):
    pass


def assets_dir(root: Path) -> Path:
    return root / "assets"


def asset_path(root: Path, asset_id: str) -> Path:
    return assets_dir(root) / f"{asset_id}.yaml"


def validate_id(asset_id: str) -> None:
    if not _ID_RE.match(asset_id):
        raise RegistryError(
            f"invalid id {asset_id!r}: use lowercase letters, digits, '-' and '_'"
        )


def create(root: Path, asset_id: str, asset_type: str, *, scene_ref=None,
           character=None, note=None) -> dict:
    validate_id(asset_id)
    if asset_type not in TYPES:
        raise RegistryError(f"unknown type {asset_type!r}; expected one of {TYPES}")
    path = asset_path(root, asset_id)
    if path.exists():
        raise RegistryError(f"asset {asset_id!r} already exists ({path})")
    data: dict = {"id": asset_id, "type": asset_type, "status": "brief"}
    if scene_ref:
        data["scene_ref"] = scene_ref
    if character:
        data["character"] = character
    if note:
        data["note"] = note
    data["revisions"] = []
    save(root, data)
    return data


def load(root: Path, asset_id: str) -> dict:
    validate_id(asset_id)
    path = asset_path(root, asset_id)
    if not path.is_file():
        raise RegistryError(f"no such asset: {asset_id!r}")
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or "id" not in data or "type" not in data:
        raise RegistryError(f"malformed registry file: {path}")
    data.setdefault("revisions", [])
    if data.get("status") not in state.STATUSES:
        raise RegistryError(f"bad status {data.get('status')!r} in {path}")
    return data


def save(root: Path, data: dict) -> None:
    ordered = {k: data[k] for k in
               ("id", "type", "scene_ref", "character", "note", "status",
                "revisions", "exports") if k in data}
    asset_path(root, data["id"]).write_text(
        yaml.dump(ordered, sort_keys=False, allow_unicode=True)
    )


def list_assets(root: Path) -> list[dict]:
    out = []
    d = assets_dir(root)
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.yaml")):
        try:
            out.append(load(root, p.stem))
        except RegistryError:
            continue
    return out


def latest_revision(data: dict) -> dict | None:
    return data["revisions"][-1] if data["revisions"] else None


def find_revision(data: dict, rev: int | None) -> dict:
    """Revision by number, or the latest when *rev* is None."""
    if not data["revisions"]:
        raise RegistryError(f"asset {data['id']!r} has no revisions yet")
    if rev is None:
        return data["revisions"][-1]
    for r in data["revisions"]:
        if r["rev"] == rev:
            return r
    raise RegistryError(f"asset {data['id']!r} has no revision {rev}")


def next_rev(data: dict) -> int:
    return max((r["rev"] for r in data["revisions"]), default=0) + 1

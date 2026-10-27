"""Deterministic gates: mechanical checks over staged revisions.

Gate names: checksum, provenance, shape (image/video/mesh/text), audio.
Each gate yields pass/fail plus a human-readable reason.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from . import media, store
from .forge import DEFAULT_GATE_CONFIG

IMAGE_TYPES = {"image", "sprite"}
VIDEO_TYPES = {"video"}
MESH_TYPES = {"mesh"}
TEXT_TYPES = {"story"}
AUDIO_TYPES = {"music", "sfx", "voice"}

IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}
AUDIO_EXTS = {"wav", "mp3", "flac", "ogg"}
TEXT_EXTS = {"md", "txt"}


def load_config(root: Path) -> dict:
    cfg = dict(DEFAULT_GATE_CONFIG)
    path = root / "gates" / "config.yaml"
    if path.is_file():
        user = yaml.safe_load(path.read_text()) or {}
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k] = {**cfg[k], **v}
            else:
                cfg[k] = v
    return cfg


class Result:
    def __init__(self) -> None:
        self.checks: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append((name, ok, detail))

    @property
    def passed(self) -> bool:
        return all(ok for _, ok, _ in self.checks)

    def summary(self) -> tuple[dict, list[str]]:
        gates = {name: ("pass" if ok else "fail") for name, ok, _ in self.checks}
        reasons = [f"{name}: {detail}" for name, ok, detail in self.checks if not ok]
        return gates, reasons


def run_gates(root: Path, asset: dict, rev: dict, cfg: dict | None = None) -> dict:
    """Run all applicable gates over one revision's staged files."""
    cfg = cfg or load_config(root)
    r = Result()
    rev_dir = store.staging_dir(root, asset["id"], rev["rev"])
    atype = asset["type"]

    if cfg.get("checksum", True):
        for f in rev["files"]:
            p = rev_dir / f["name"]
            ok = p.is_file() and store.verify(p, f["checksum"])
            r.check("checksum", ok, f"{f['name']} {'matches' if ok else 'MISSING/CORRUPT'} {f['checksum'][:18]}..")

    if cfg.get("provenance", True):
        backend = rev.get("backend")
        r.check("provenance", bool(backend),
                f"backend={backend}" if backend else "no backend recorded")

    for f in rev["files"]:
        p = rev_dir / f["name"]
        if not p.is_file():
            continue
        ext = p.suffix.lower().lstrip(".")
        kind = ("image" if ext in IMAGE_EXTS else
                "audio" if ext in AUDIO_EXTS else
                "text" if ext in TEXT_EXTS else None)
        if atype in IMAGE_TYPES:
            _gate_image(r, f, p, ext, kind, atype, cfg)
        elif atype in AUDIO_TYPES:
            _gate_audio(r, f, p, ext, cfg)
        elif atype in VIDEO_TYPES or atype in MESH_TYPES:
            section = "video" if atype in VIDEO_TYPES else "mesh"
            fmts = cfg[section]["formats"]
            r.check("shape", ext in fmts, f"{f['name']}: .{ext} {'in' if ext in fmts else 'NOT in'} allowed {fmts}")
        elif atype in TEXT_TYPES:
            _gate_text(r, f, p, ext, cfg)
        else:
            r.check("shape", False, f"{f['name']}: unhandled asset type {atype!r}")

    gates, reasons = r.summary()
    return {"gates": gates, "passed": r.passed, "reasons": reasons}


def _gate_image(r: Result, f: dict, p: Path, ext: str, kind, atype: str, cfg: dict) -> None:
    name = f["name"]
    if kind != "image":
        r.check("shape", False, f"{name}: not a recognized image file (.{ext})")
        return
    fmts = cfg["image"]["formats"]
    r.check("shape", ext in fmts, f"{name}: .{ext} {'in' if ext in fmts else 'NOT in'} allowed {fmts}")
    info = media.image_info(p.read_bytes())
    if info is None:
        r.check("shape", False, f"{name}: unparseable image header")
        return
    w, h = info["width"], info["height"]
    c = cfg["image"]
    ok = c["min_width"] <= w <= c["max_width"] and c["min_height"] <= h <= c["max_height"]
    r.check("shape", ok, f"{name}: {w}x{h} (allowed {c['min_width']}..{c['max_width']} x {c['min_height']}..{c['max_height']})")
    if atype == "sprite" and cfg.get("sprite", {}).get("requires_alpha", False):
        r.check("shape", info["alpha"],
                f"{name}: sprite requires alpha, got channels={info['channels']} alpha={info['alpha']}")


def _gate_audio(r: Result, f: dict, p: Path, ext: str, cfg: dict) -> None:
    name = f["name"]
    fmts = cfg["audio"]["formats"]
    r.check("audio", ext in fmts, f"{name}: .{ext} {'in' if ext in fmts else 'NOT in'} allowed {fmts}")
    if ext != "wav":
        r.check("audio", False, f"{name}: deterministic audio probes support wav only (got .{ext})")
        return
    info = media.wav_info(p)
    if info is None:
        r.check("audio", False, f"{name}: unparseable wav")
        return
    c = cfg["audio"]
    d = info["duration"]
    r.check("audio", c["min_duration"] <= d <= c["max_duration"],
            f"{name}: duration {d:.2f}s (allowed {c['min_duration']}..{c['max_duration']}s)")
    if info["rms"] is not None:
        r.check("audio", c["min_rms"] <= info["rms"] <= c["max_rms"],
                f"{name}: rms {info['rms']:.4f} (allowed {c['min_rms']}..{c['max_rms']})")
        r.check("audio", info["clip_ratio"] <= c["max_clip_ratio"],
                f"{name}: clip ratio {info['clip_ratio']:.4f} (max {c['max_clip_ratio']})")


def _gate_text(r: Result, f: dict, p: Path, ext: str, cfg: dict) -> None:
    name = f["name"]
    fmts = cfg["text"]["formats"]
    r.check("shape", ext in fmts, f"{name}: .{ext} {'in' if ext in fmts else 'NOT in'} allowed {fmts}")
    try:
        text = p.read_text(encoding="utf-8")
        ok = len(text) >= cfg["text"]["min_chars"]
        r.check("shape", ok, f"{name}: {len(text)} chars (min {cfg['text']['min_chars']})")
    except UnicodeDecodeError:
        r.check("shape", False, f"{name}: not valid UTF-8")

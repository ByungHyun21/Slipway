"""Media probing with stdlib only: image header parsing, WAV analysis."""

from __future__ import annotations

import struct
import wave
from pathlib import Path


def image_info(data: bytes) -> dict | None:
    """Parse format/dimensions/alpha from image bytes. None if not an image."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return _png(data)
    if data[:3] == b"\xff\xd8\xff":
        return _jpeg(data)
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return _gif(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp(data)
    return None


def _chunk_u32be(b: bytes, off: int) -> int:
    return struct.unpack_from(">I", b, off)[0]


def _png(b: bytes) -> dict | None:
    if len(b) < 33 or b[12:16] != b"IHDR":
        return None
    w, h = _chunk_u32be(b, 16), _chunk_u32be(b, 20)
    bit_depth, color_type = b[24], b[25]
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        return None
    alpha = color_type in (4, 6) or b"tRNS" in b[: len(b)]
    return {"format": "png", "width": w, "height": h, "alpha": alpha,
            "channels": channels, "bit_depth": bit_depth}


def _jpeg(b: bytes) -> dict | None:
    i = 2
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB,
           0xCD, 0xCE, 0xCF}
    while i < len(b) - 9:
        if b[i] != 0xFF:
            i += 1
            continue
        marker = b[i + 1]
        if marker in sof:
            h, w = struct.unpack_from(">HH", b, i + 5)
            ncomp = b[i + 9]
            return {"format": "jpg", "width": w, "height": h, "alpha": False,
                    "channels": ncomp, "bit_depth": b[i + 4]}
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD9:
            i += 2
            continue
        if i + 4 > len(b):
            break
        i += 2 + struct.unpack_from(">H", b, i + 2)[0]
    return None


def _gif(b: bytes) -> dict | None:
    if len(b) < 10:
        return None
    w, h = struct.unpack_from("<HH", b, 6)
    alpha = False
    i = 13
    if i < len(b) and b[i] & 0x80:  # global color table follows
        i += 3 * (2 << (b[i] & 0x07))
    while i < len(b) - 6:
        if b[i] == 0x21 and b[i + 1] == 0xF9 and b[i + 2] >= 4:
            alpha = alpha or bool(b[i + 3] & 0x01)
        if b[i] == 0x21 or b[i] == 0x22:  # extension: skip sub-blocks
            i += 2
            while i < len(b) and b[i]:
                i += 1 + b[i]
            i += 1
        elif b[i] == 0x2C:  # image descriptor
            i += 10
            if i < len(b) and b[i] & 0x80:
                i += 3 * (2 << (b[i] & 0x07))
            i += 1
            while i < len(b) and b[i]:
                i += 1 + b[i]
            i += 1
        else:
            i += 1
    return {"format": "gif", "width": w, "height": h, "alpha": alpha,
            "channels": 4 if alpha else 3, "bit_depth": 8}


def _webp(b: bytes) -> dict | None:
    if len(b) < 30:
        return None
    fourcc = b[12:16]
    if fourcc == b"VP8X":
        w = 1 + int.from_bytes(b[24:27], "little")
        h = 1 + int.from_bytes(b[27:30], "little")
        flags = b[20]
        alpha = bool(flags & 0x10)
        return {"format": "webp", "width": w, "height": h, "alpha": alpha,
                "channels": 4 if alpha else 3, "bit_depth": 8}
    if fourcc == b"VP8L":
        bits = int.from_bytes(b[21:26], "little")
        w, h = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        alpha = bool((bits >> 30) & 1)
        return {"format": "webp", "width": w, "height": h, "alpha": alpha,
                "channels": 4 if alpha else 3, "bit_depth": 8}
    if fourcc == b"VP8 ":
        w = struct.unpack_from("<H", b, 26)[0] & 0x3FFF
        h = struct.unpack_from("<H", b, 28)[0] & 0x3FFF
        return {"format": "webp", "width": w, "height": h, "alpha": False,
                "channels": 3, "bit_depth": 8}
    return None


def wav_info(path: Path | str) -> dict | None:
    """Duration, channels, loudness (RMS), clipping ratio for a WAV file."""
    try:
        with wave.open(str(path), "rb") as wf:
            n, rate, ch, width = (wf.getnframes(), wf.getframerate(),
                                  wf.getnchannels(), wf.getsampwidth())
            frames = wf.readframes(n)
    except Exception:
        return None
    if rate == 0:
        return None
    duration = n / rate
    if width == 2:
        samples = struct.unpack(f"<{len(frames) // 2}h", frames[: len(frames) // 2 * 2])
        full = 32768
    elif width == 1:
        samples = [s - 128 for s in frames]
        full = 128
    elif width == 4:
        samples = struct.unpack(f"<{len(frames) // 4}i", frames[: len(frames) // 4 * 4])
        full = 2147483648
    else:
        return {"format": "wav", "duration": duration, "channels": ch,
                "sample_width": width, "rms": None, "clip_ratio": None}
    if not samples:
        rms, clip = 0.0, 0.0
    else:
        rms = (sum(s * s for s in samples) / len(samples)) ** 0.5 / full
        peak = full - 1 if width == 2 else full
        clipped = sum(1 for s in samples if abs(s) >= peak)
        clip = clipped / len(samples)
    return {"format": "wav", "duration": duration, "channels": ch,
            "sample_width": width, "rms": rms, "clip_ratio": clip}

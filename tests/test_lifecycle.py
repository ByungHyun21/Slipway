"""Lifecycle regression tests: full loop plus gate boundary behavior."""

from __future__ import annotations

import io
import json
import math
import os
import struct
import sys
import tempfile
import threading
import unittest
import urllib.request
import wave
import zlib
from contextlib import redirect_stdout, redirect_stderr
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from slipway import cli, forge, model, serve


def make_png(w: int = 32, h: int = 32, rgba: bool = True) -> bytes:
    ct, ch = (6, 4) if rgba else (2, 3)
    raw = b"".join(b"\x00" + bytes([91] * (w * ch)) for _ in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, ct, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_wav(seconds: float = 1.0, rate: int = 8000, clip: bool = False,
             quiet: bool = False) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        n = int(seconds * rate)
        amp = 1 if quiet else (32767 if clip else 8000)
        frames = bytearray()
        for i in range(n):
            v = int(amp * math.sin(2 * math.pi * 440 * i / rate))
            if clip and i % 2 == 0:
                v = 32767  # every other sample pinned at full scale
            frames += struct.pack("<h", v)
        wf.writeframes(bytes(frames))
    return buf.getvalue()


class SlipTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.forge = forge.init(self.root / "forge")
        self.prev_cwd = Path.cwd()
        os.chdir(self.forge)

    def tearDown(self):
        os.chdir(self.prev_cwd)
        self.tmp.cleanup()

    def slip(self, *argv: str) -> tuple[int, str]:
        err = io.StringIO()
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue() + err.getvalue()

    def asset(self, asset_id: str) -> dict:
        return model.load(self.forge, asset_id)


class TestLifecycle(SlipTestCase):
    def test_full_loop_to_export(self):
        png = self.root / "hero.png"
        png.write_bytes(make_png())

        self.assertEqual(self.slip("brief", "hero_idle", "--type", "sprite")[0], 0)
        self.assertEqual(self.asset("hero_idle")["status"], "brief")

        code, _ = self.slip("add", "hero_idle", str(png), "--backend", "comfyui",
                            "--param", "seed=812", "--param", "prompt=idle loop")
        self.assertEqual(code, 0)
        a = self.asset("hero_idle")
        self.assertEqual(a["status"], "gated")  # auto-gate on add passed
        rev = a["revisions"][0]
        self.assertEqual(rev["params"], {"seed": 812, "prompt": "idle loop"})
        self.assertTrue(rev["files"][0]["checksum"].startswith("sha256:"))

        self.assertEqual(self.slip("approve", "hero_idle")[0], 0)
        a = self.asset("hero_idle")
        self.assertEqual(a["status"], "approved")
        self.assertTrue((self.forge / "approved" / "hero_idle" / "1" / "hero.png").is_file())

        target = self.root / "game"
        self.assertEqual(self.slip("export", "hero_idle", "--to", str(target))[0], 0)
        a = self.asset("hero_idle")
        self.assertEqual(a["status"], "exported")
        self.assertTrue((target / "hero_idle" / "1" / "hero.png").is_file())

    def test_bounce_back_on_failed_gate(self):
        bad = self.root / "opaque.png"
        bad.write_bytes(make_png(rgba=False))  # sprite requires alpha
        self.slip("brief", "opaque", "--type", "sprite")
        code, out = self.slip("add", "opaque", str(bad), "--backend", "comfyui")
        self.assertEqual(code, 1)
        self.assertIn("alpha", out)
        a = self.asset("opaque")
        self.assertEqual(a["status"], "generated")  # never reaches gated
        self.assertEqual(a["revisions"][0]["gates"]["shape"], "fail")
        # approval must be refused
        self.assertEqual(self.slip("approve", "opaque")[0], 1)
        # export must be refused even if forced
        self.assertEqual(self.slip("export", "opaque", "--to", str(self.root / "g"))[0], 1)

    def test_audio_gates(self):
        ok = self.root / "ok.wav"
        ok.write_bytes(make_wav())
        long_wav = self.root / "long.wav"
        long_wav.write_bytes(make_wav(seconds=400))
        clipped = self.root / "clip.wav"
        clipped.write_bytes(make_wav(clip=True))

        self.slip("brief", "sfx_ok", "--type", "sfx")
        self.assertEqual(self.slip("add", "sfx_ok", str(ok), "--backend", "stable-audio")[0], 0)
        self.assertEqual(self.asset("sfx_ok")["status"], "gated")

        self.slip("brief", "sfx_long", "--type", "sfx")
        code, out = self.slip("add", "sfx_long", str(long_wav), "--backend", "stable-audio")
        self.assertEqual(code, 1)
        self.assertIn("duration", out)

        self.slip("brief", "sfx_clip", "--type", "sfx")
        code, out = self.slip("add", "sfx_clip", str(clipped), "--backend", "stable-audio")
        self.assertEqual(code, 1)
        self.assertIn("clip", out)

    def test_checksum_tamper_detected(self):
        png = self.root / "a.png"
        png.write_bytes(make_png())
        self.slip("brief", "tamper", "--type", "image")
        self.slip("add", "tamper", str(png), "--backend", "comfyui")
        staged = self.forge / "staging" / "tamper" / "1" / "a.png"
        staged.write_bytes(make_png(w=64, h=64))
        code, _ = self.slip("gate", "tamper")
        self.assertEqual(code, 1)
        self.assertEqual(self.asset("tamper")["status"], "generated")

    def test_second_revision_and_rev_select(self):
        png1, png2 = self.root / "v1.png", self.root / "v2.png"
        png1.write_bytes(make_png(32, 32))
        png2.write_bytes(make_png(64, 64))
        self.slip("brief", "multi", "--type", "image")
        self.slip("add", "multi", str(png1), "--backend", "comfyui")
        self.slip("add", "multi", str(png2), "--backend", "comfyui")
        self.assertEqual(self.slip("approve", "multi", "--rev", "1")[0], 0)
        self.assertTrue((self.forge / "approved" / "multi" / "1" / "v1.png").is_file())
        self.assertFalse((self.forge / "approved" / "multi" / "2").exists())

    def test_story_asset(self):
        script = self.root / "ch03.md"
        script.write_text("# Scene 3\n\nHero enters.")
        self.slip("brief", "ch03_script", "--type", "story",
                  "--scene", "canon/story/ch03.md")
        self.assertEqual(self.slip("add", "ch03_script", str(script), "--backend", "llm")[0], 0)
        a = self.asset("ch03_script")
        self.assertEqual(a["status"], "gated")
        self.assertEqual(a["scene_ref"], "canon/story/ch03.md")


class TestServe(SlipTestCase):
    def setUp(self):
        super().setUp()
        png = self.root / "a.png"
        png.write_bytes(make_png())
        self.slip("brief", "dl", "--type", "image")
        self.slip("add", "dl", str(png), "--backend", "comfyui")
        self.slip("approve", "dl")

        unapproved = self.root / "raw.png"
        unapproved.write_bytes(make_png(rgba=False))
        self.slip("brief", "opa", "--type", "sprite")
        self.slip("add", "opa", str(unapproved), "--backend", "comfyui")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.make_handler(self.forge))
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def get(self, path: str):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            assert r.status == 200
            return r.read()

    def test_index_lists_approved_only(self):
        body = self.get("/").decode()
        self.assertIn("/download/dl/1/a.png", body)          # approved revision is downloadable
        self.assertIn('class="stamp approved"', body)
        self.assertNotIn("/download/opa", body)               # 'opa' failed gates: never downloadable
        self.assertIn("gates not passed", body)              # failed-gate rev shows disabled approve stub
        self.assertIn("disabled", body)

    def test_download_approved_file_and_zip(self):
        data = self.get("/download/dl/1/a.png")
        self.assertEqual(data, make_png())
        self.assertIn(b"PK", self.get("/download/dl/1.zip")[:2])
        allz = self.get("/download/all.zip")
        self.assertIn(b"dl/1/a.png", allz)
        self.assertNotIn(b"opa/", allz)

    def test_unapproved_download_404(self):
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError) as ctx:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/download/opa/1/raw.png")
        self.assertEqual(ctx.exception.code, 404)

    def test_traversal_blocked(self):
        from urllib.error import HTTPError
        for path in ("/download/dl/1/../../assets/dl.yaml",
                     "/download/dl/1/%2e%2e%2fassets%2fdl.yaml"):
            with self.assertRaises(HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}")
            self.assertEqual(ctx.exception.code, 404)

    def test_json_api(self):
        data = json.loads(self.get("/api/assets"))
        dl = next(a for a in data if a["id"] == "dl")
        self.assertEqual(dl["status"], "approved")
        self.assertEqual(dl["approved_revisions"], [1])

    def test_static_route_serves_vendored_js(self):
        body = self.get("/static/model-viewer.min.js")
        self.assertGreater(len(body), 100_000)  # the ~935KB vendored library
        self.assertIn(b"model-viewer", body)

    def test_static_traversal_blocked(self):
        from urllib.error import HTTPError
        for path in ("/static/../slipway/cli.py", "/static/%2e%2e%2fmodel.py"):
            with self.assertRaises(HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}")
            self.assertEqual(ctx.exception.code, 404)


class TestMedia(unittest.TestCase):
    def test_png_parsing(self):
        from slipway import media
        info = media.image_info(make_png(40, 20, rgba=True))
        self.assertEqual((info["width"], info["height"], info["alpha"]), (40, 20, True))
        info = media.image_info(make_png(8, 8, rgba=False))
        self.assertFalse(info["alpha"])
        self.assertIsNone(media.image_info(b"not an image"))

    def test_gif_parsing(self):
        from slipway import media
        gif = b"GIF89a" + struct.pack("<HH", 30, 20) + b"\x00" * 10
        info = media.image_info(gif)
        self.assertEqual((info["width"], info["height"]), (30, 20))


if __name__ == "__main__":
    unittest.main()

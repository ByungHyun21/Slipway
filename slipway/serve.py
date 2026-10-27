"""HTTP catalog + download server. Serves approved artifacts only."""

from __future__ import annotations

import io
import json
import shutil
import mimetypes
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from . import model, web


def _zip(entries: list[tuple[str, Path]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for arcname, p in entries:
            z.write(p, arcname)
    return buf.getvalue()


EXTRA_TYPES = {
    ".webp": "image/webp", ".webm": "video/webm", ".mov": "video/quicktime",
    ".mp4": "video/mp4", ".m4a": "audio/mp4", ".flac": "audio/flac",
    ".opus": "audio/ogg", ".ogv": "video/ogg", ".svg": "image/svg+xml",
}


def guess_ctype(name: str) -> str:
    return EXTRA_TYPES.get(Path(name).suffix.lower()) or \
        mimetypes.guess_type(name)[0] or "application/octet-stream"


def make_handler(root: Path) -> type[BaseHTTPRequestHandler]:
    approved_root = (root / "approved").resolve()
    previews_root = (root / "previews").resolve()
    static_root = (Path(__file__).parent / "static").resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "slipway/0.1"

        # ---- plumbing -------------------------------------------------
        def do_GET(self) -> None:
            try:
                self._route()
            except FileNotFoundError:
                self.send_error(404, "not found")
            except Exception as e:  # keep the server alive on bad requests
                self.send_error(500, f"internal error: {e}")

        def _send(self, code: int, ctype: str, body: bytes,
                  filename: str | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            if filename:
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def _rev_dir(self, asset_id: str, rev: str) -> Path:
            d = (approved_root / asset_id / rev).resolve()
            if not str(d).startswith(str(approved_root) + "/") or not d.is_dir():
                raise FileNotFoundError(d)
            return d

        # ---- routes ---------------------------------------------------
        def _route(self) -> None:
            parts = [unquote(p) for p in self.path.split("?")[0].split("/") if p]
            if not parts:
                return self._index()
            if parts == ["api", "assets"]:
                return self._api_assets()
            if parts[0] == "download":
                if parts[1:] == ["all.zip"]:
                    return self._download_all()
                if len(parts) == 3 and parts[2].endswith(".zip"):
                    return self._download_zip(parts[1], parts[2][:-4])
                if len(parts) == 4:
                    return self._download_file(parts[1], parts[2], parts[3])
            if parts[0] == "static" and len(parts) == 2:
                return self._serve_static(parts[1])
            if parts[0] == "previews" and len(parts) == 4:
                return self._serve_preview(parts[1], parts[2], parts[3])
            raise FileNotFoundError(self.path)

        def _serve_static(self, name: str) -> None:
            f = (static_root / name).resolve()
            if not str(f).startswith(str(static_root) + "/") or not f.is_file():
                raise FileNotFoundError(f)
            self.send_response(200)
            self.send_header("Content-Type", guess_ctype(name))
            self.send_header("Content-Length", str(f.stat().st_size))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            with f.open("rb") as fh:
                shutil.copyfileobj(fh, self.wfile)

        def _serve_preview(self, asset_id: str, rev: str, name: str) -> None:
            d = (previews_root / asset_id / rev).resolve()
            if not str(d).startswith(str(previews_root) + "/"):
                raise FileNotFoundError(d)
            f = (d / name).resolve()
            if not str(f).startswith(str(d) + "/") or not f.is_file():
                raise FileNotFoundError(f)
            self._send(200, guess_ctype(name), f.read_bytes())

        def _index(self) -> None:
            page = web.render_catalog(root)
            self._send(200, "text/html; charset=utf-8", page.encode())

        def _api_assets(self) -> None:
            data = [{"id": a["id"], "type": a["type"], "status": a["status"],
                     "approved_revisions": [r["rev"] for r in a["revisions"] if r.get("approved_at")]}
                    for a in model.list_assets(root)]
            self._send(200, "application/json", json.dumps(data).encode())

        def _download_file(self, asset_id: str, rev: str, name: str) -> None:
            d = self._rev_dir(asset_id, rev)
            f = (d / name).resolve()
            if not str(f).startswith(str(d) + "/") or not f.is_file():
                raise FileNotFoundError(f)
            ctype = guess_ctype(name)
            size = f.stat().st_size
            inline = "inline" in self.path.partition("?")[2]
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes="):
                try:
                    s_str, _, e_str = rng[6:].partition("-")
                    start = int(s_str) if s_str else 0
                    end = int(e_str) if e_str else size - 1
                except ValueError:
                    start, end = 0, size - 1
                else:
                    if start <= end and start < size:
                        end = min(end, size - 1)
                        self.send_response(206)
                        self.send_header("Content-Type", ctype)
                        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                        self.send_header("Content-Length", str(end - start + 1))
                        self.send_header("Accept-Ranges", "bytes")
                        self._disposition(name, inline)
                        self.end_headers()
                        with f.open("rb") as fh:
                            fh.seek(start)
                            remaining = end - start + 1
                            while remaining > 0:
                                chunk = fh.read(min(1 << 16, remaining))
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                remaining -= len(chunk)
                        return
                self.send_error(416, "range not satisfiable")
                self.close_connection = True
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self._disposition(name, inline)
            self.end_headers()
            with f.open("rb") as fh:
                while True:
                    chunk = fh.read(1 << 16)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

        def _disposition(self, name: str, inline: bool) -> None:
            mode = "inline" if inline else "attachment"
            self.send_header("Content-Disposition", f'{mode}; filename="{name}"')

        def _download_zip(self, asset_id: str, rev: str) -> None:
            d = self._rev_dir(asset_id, rev)
            entries = [(p.name, p) for p in sorted(d.iterdir()) if p.is_file()]
            if not entries:
                raise FileNotFoundError(d)
            self._send(200, "application/zip", _zip(entries),
                       filename=f"{asset_id}_rev{rev}.zip")

        def _download_all(self) -> None:
            entries = []
            if approved_root.is_dir():
                for asset_dir in sorted(approved_root.iterdir()):
                    if not asset_dir.is_dir():
                        continue
                    for rev_dir in sorted(asset_dir.iterdir()):
                        if not rev_dir.is_dir():
                            continue
                        for f in sorted(rev_dir.iterdir()):
                            if f.is_file():
                                entries.append(
                                    (f"{asset_dir.name}/{rev_dir.name}/{f.name}", f))
            self._send(200, "application/zip", _zip(entries), filename="slipway-approved.zip")

    return Handler


def serve(root: Path, host: str = "127.0.0.1", port: int = 8321) -> None:
    httpd = ThreadingHTTPServer((host, port), make_handler(root))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()

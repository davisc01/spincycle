"""
Standalone HTTP server for managing config/library.csv without ssh/scp, and
for triggering/monitoring a video_cache.warm_cache() run from the LAN.

Not imported by main.py -- run it manually (or as its own systemd service)
only when you want to push a new library or pre-warm the cache:

    python3 library_server.py            # binds 0.0.0.0:8080
    python3 library_server.py --port 9000

SECURITY NOTE: there is no authentication. This is meant for trusted
home-LAN use only -- the same trust model as ssh/scp today. Don't expose
this port beyond your LAN.
"""
import argparse
import html
import os
import shutil
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
import library
import video_cache

_warm_lock = threading.Lock()
_warm_state = {"running": False, "current": 0, "total": 0, "label": ""}


def parse_multipart_file(content_type, body):
    """Extract the bytes of the single uploaded file from a
    multipart/form-data body. Deliberately hand-rolled (rather than the
    deprecated/removed cgi.FieldStorage) since we only ever need one file
    field."""
    if not content_type or "multipart/form-data" not in content_type:
        raise ValueError("expected multipart/form-data")

    boundary = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part[len("boundary="):].strip('"')
    if not boundary:
        raise ValueError("no boundary in Content-Type header")

    boundary_bytes = ("--" + boundary).encode()
    for segment in body.split(boundary_bytes):
        # Strip exactly the one leading CRLF that separates the boundary
        # line from the part -- .strip() would also eat legitimate
        # trailing newlines from the file content below.
        if segment.startswith(b"\r\n"):
            segment = segment[2:]
        if not segment or segment.startswith(b"--"):
            continue
        if b"\r\n\r\n" not in segment:
            continue
        headers_blob, content = segment.split(b"\r\n\r\n", 1)
        if b"filename=" in headers_blob:
            # Only the single trailing CRLF that precedes the next
            # boundary is part of the multipart framing -- anything
            # before that (including a trailing newline in the uploaded
            # file itself) must survive.
            if content.endswith(b"\r\n"):
                content = content[:-2]
            return content

    raise ValueError("no file part found in upload")


def _log_failure(label, url, err):
    config.ensure_dirs()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp}  {label}  {url}  ERROR: {err}\n"
    with open(config.WARM_CACHE_LOG, "a", encoding="utf-8") as f:
        f.write(line)
    print(f"[warm-cache] FAILED: {label} ({url}): {err}")


def _run_warm_cache():
    with _warm_lock:
        if _warm_state["running"]:
            return
        _warm_state.update(running=True, current=0, total=0, label="")

    try:
        lib = library.load_library(config.LIBRARY_FILE)
        tracks = library.all_tracks(lib)

        def on_progress(i, total, label, err):
            with _warm_lock:
                _warm_state.update(current=i, total=total, label=label)
            if err is not None:
                url = tracks[i - 1]["url"] if i - 1 < len(tracks) else ""
                _log_failure(label, url, err)

        video_cache.warm_cache(lib, on_progress=on_progress)
    finally:
        with _warm_lock:
            _warm_state["running"] = False


def _recent_failures(limit=20):
    if not os.path.exists(config.WARM_CACHE_LOG):
        return []
    with open(config.WARM_CACHE_LOG, "r", encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f if line.strip()]
    return list(reversed(lines[-limit:]))


def _render_index():
    if os.path.exists(config.LIBRARY_FILE):
        stat = os.stat(config.LIBRARY_FILE)
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        library_status = f"{stat.st_size} bytes, last modified {mtime}"
    else:
        library_status = "not found"

    with _warm_lock:
        state = dict(_warm_state)

    if state["running"]:
        warm_status = f"Running: {state['current']}/{state['total']} — {html.escape(state['label'])}"
        refresh_tag = '<meta http-equiv="refresh" content="5">'
    else:
        warm_status = "Idle"
        refresh_tag = ""

    failures = _recent_failures()
    if failures:
        failures_html = "\n".join(f"<li>{html.escape(line)}</li>" for line in failures)
    else:
        failures_html = "<li>(none)</li>"

    return f"""<!doctype html>
<html>
<head><title>Jukebox library manager</title>{refresh_tag}</head>
<body>
<h1>Jukebox library manager</h1>

<h2>Current library.csv</h2>
<p>{html.escape(library_status)}</p>
<form method="POST" action="/upload" enctype="multipart/form-data">
  <input type="file" name="csv" accept=".csv">
  <button type="submit">Upload replacement</button>
</form>

<h2>Cache warming</h2>
<p>Status: {warm_status}</p>
<form method="POST" action="/warm-cache">
  <button type="submit">Warm cache</button>
</form>

<h3>Recent failures (config.WARM_CACHE_LOG)</h3>
<ul>
{failures_html}
</ul>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send_html(self, status, body):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path == "/":
            self._send_html(200, _render_index())
        else:
            self._send_html(404, "<h1>Not found</h1>")

    def do_POST(self):
        if self.path == "/upload":
            self._handle_upload()
        elif self.path == "/warm-cache":
            self._handle_warm_cache()
        else:
            self._send_html(404, "<h1>Not found</h1>")

    def _handle_upload(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")

        tmp_path = config.LIBRARY_FILE + ".upload.tmp"
        try:
            file_bytes = parse_multipart_file(content_type, body)
            with open(tmp_path, "wb") as f:
                f.write(file_bytes)
            lib = library.load_library(tmp_path)
        except Exception as e:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            self._send_html(
                400,
                f"<h1>Upload rejected</h1><p>{html.escape(str(e))}</p>"
                '<p><a href="/">Back</a></p>',
            )
            return

        if os.path.exists(config.LIBRARY_FILE):
            shutil.copy2(config.LIBRARY_FILE, config.LIBRARY_FILE + ".bak")
        os.replace(tmp_path, config.LIBRARY_FILE)

        genres = len(lib)
        eras = sum(len(e) for e in lib.values())
        tracks = len(library.all_tracks(lib))
        self._send_html(
            200,
            f"<h1>Upload accepted</h1>"
            f"<p>{genres} genre(s), {eras} genre/era combination(s), {tracks} track(s).</p>"
            '<p><a href="/">Back</a></p>',
        )

    def _handle_warm_cache(self):
        with _warm_lock:
            already_running = _warm_state["running"]
        if not already_running:
            threading.Thread(target=_run_warm_cache, daemon=True).start()

        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, fmt, *args):
        print(f"[library_server] {self.address_string()} - {fmt % args}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    config.ensure_dirs()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving on http://{args.host}:{args.port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

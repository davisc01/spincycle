"""
Standalone HTTP server serving Spin Cycle's web remote (web/index.html):
genre/era selection, skip/stop, and a Library panel for managing the
track library (config.LIBRARY_DB) and cache warming.

Not imported when menu.py's terminal keyboard mode is run standalone, but
started automatically by main.py alongside a SpinCycleController -- see that
file. Also runnable standalone (without a controller) for library
maintenance only:

    python3 library_server.py            # binds 0.0.0.0:80
    python3 library_server.py --port 9000

Port 80 is privileged on Linux -- binding it needs either root or the
cap_net_bind_service capability. Don't run this whole process as root
(see the security note below); instead grant the capability to the
interpreter once:

    sudo setcap 'cap_net_bind_service=+ep' $(readlink -f venv/bin/python3)

(Re-run that after rebuilding the venv -- a new python3 binary means the
capability grant needs reapplying.) See README.md's "Setup on the Pi"
section for the full explanation.

SECURITY NOTE: there is no authentication. This is meant for trusted
home-LAN use only -- the same trust model as ssh/scp today. Don't expose
this port beyond your LAN.
"""
import argparse
import csv
import html
import io
import json
import os
import shutil
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
import library
import video_cache

_warm_lock = threading.Lock()
_warm_state = {"running": False, "current": 0, "total": 0, "label": "", "last_run": None}

# Serializes the read-modify-write handlers below (upload, add/edit/delete
# track) so two concurrent Library-panel requests (e.g. two tabs open)
# can't race and silently clobber each other's change to LIBRARY_DB.
_library_lock = threading.Lock()

# Sanity caps on request bodies -- this server has no auth, so an
# unbounded Content-Length read is a memory-exhaustion risk (notable on a
# Pi 4). Generous for legitimate use: JSON payloads here are just a genre/
# era/url string, and even a library.csv with thousands of rows is well
# under a couple MB.
_MAX_JSON_BODY_BYTES = 1 * 1024 * 1024
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024

_WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
_IMAGES_DIR = os.path.join(os.path.dirname(__file__), "images")
_STATIC_FILES = {
    "/": (os.path.join(_WEB_DIR, "index.html"), "text/html; charset=utf-8"),
    "/style.css": (os.path.join(_WEB_DIR, "style.css"), "text/css; charset=utf-8"),
    "/app.js": (os.path.join(_WEB_DIR, "app.js"), "application/javascript; charset=utf-8"),
    "/player": (os.path.join(_WEB_DIR, "player.html"), "text/html; charset=utf-8"),
    "/player.js": (os.path.join(_WEB_DIR, "player.js"), "application/javascript; charset=utf-8"),
    "/images/spin_cycle_logo_full.png": (os.path.join(_IMAGES_DIR, "spin_cycle_logo_full.png"), "image/png"),
    "/images/spin_cycle_icon_128.png": (os.path.join(_IMAGES_DIR, "spin_cycle_icon_128.png"), "image/png"),
    "/images/spin_cycle_icon_256.png": (os.path.join(_IMAGES_DIR, "spin_cycle_icon_256.png"), "image/png"),
    "/images/spin_cycle_icon_512.png": (os.path.join(_IMAGES_DIR, "spin_cycle_icon_512.png"), "image/png"),
    "/images/background.jpg": (os.path.join(_IMAGES_DIR, "background.jpg"), "image/jpeg"),
    "/favicon.ico": (os.path.join(_IMAGES_DIR, "spin_cycle_icon_128.png"), "image/png"),
}


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


def start_background_warm_cache():
    """
    Kick off a cache-warm run in the background if one isn't already in
    progress. Safe to call repeatedly -- both the "Warm cache" button and
    main.py's startup call go through this, and _run_warm_cache() itself
    also no-ops under the lock if a run is already active, so a race
    between the two just results in one run either way.
    """
    with _warm_lock:
        already_running = _warm_state["running"]
    if not already_running:
        threading.Thread(target=_run_warm_cache, daemon=True).start()


def _run_warm_cache():
    with _warm_lock:
        if _warm_state["running"]:
            return
        _warm_state.update(running=True, current=0, total=0, label="")

    try:
        lib = library.load_library(config.LIBRARY_DB)

        def on_progress(i, total, genre, era, track, err):
            label = f"{track['artist']} - {track['song']}" if track.get("artist") else track["url"]
            with _warm_lock:
                _warm_state.update(current=i, total=total, label=label)
            # Recorded on the row itself, keyed by id (not url) -- see
            # library.set_cache_status()'s docstring for why writing this
            # once per track per run already reproduces the old
            # cache_failures.json's "only reflects the latest run"
            # behavior with no separate clear-all-first step.
            library.set_cache_status(config.LIBRARY_DB, track["id"], err)
            if err is not None:
                print(f"[warm-cache] FAILED: {label} ({track['url']}): {err}")

        video_cache.warm_cache(lib, on_progress=on_progress)
    finally:
        with _warm_lock:
            _warm_state["running"] = False
            _warm_state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _tail_lines(path, limit=50):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f if line.strip()]
    return list(reversed(lines[-limit:]))


class Handler(BaseHTTPRequestHandler):
    @property
    def controller(self):
        return getattr(self.server, "controller", None)

    @property
    def session_manager(self):
        return getattr(self.server, "session_manager", None)

    @property
    def path_no_query(self):
        # self.path includes the query string (e.g. "/player?session=foo",
        # from the "Launch Player" link) -- routing below must match on the
        # path alone, or every query-string request 404s.
        return self.path.split("?", 1)[0]

    def _send_html(self, status, body):
        self._send_bytes(status, body.encode("utf-8"), "text/html; charset=utf-8")

    def _send_json(self, status, obj):
        self._send_bytes(status, json.dumps(obj).encode("utf-8"), "application/json")

    def _send_bytes(self, status, encoded, content_type, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        if length > _MAX_JSON_BODY_BYTES:
            # Don't attempt to read/drain an oversized body -- just close
            # this connection rather than leave unread bytes to corrupt
            # framing of whatever request would come next on it.
            self.close_connection = True
            raise ValueError(f"request body too large ({length} bytes, max {_MAX_JSON_BODY_BYTES})")
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8")) if body else {}

    # -- routing ---------------------------------------------------------

    def do_GET(self):
        route = self._session_route()
        if route is not None:
            name, action = route
            if name is None:
                if self._require_session_manager():
                    self._send_json(200, self._sessions_status_list())
                return
            if action == "status":
                self._handle_session_status(name)
                return
            if action == "tracks":
                self._handle_session_tracks(name)
                return
            self._send_html(404, "<h1>Not found</h1>")
            return

        path = self.path_no_query
        if path in _STATIC_FILES:
            self._serve_static(path)
        elif path.startswith("/video/"):
            self._serve_video(path[len("/video/"):])
        elif path == "/library.csv":
            self._handle_download_csv()
        elif path == "/api/status":
            if self._require_controller():
                self._send_json(200, self.controller.status())
        elif path == "/api/tracks":
            if self._require_controller():
                self._send_json(200, self.controller.track_list())
        elif path == "/api/library-status":
            self._send_json(200, self._library_status())
        elif path == "/api/library-tracks":
            self._send_json(200, self._list_library_tracks())
        elif path == "/api/cache-status":
            with _warm_lock:
                self._send_json(200, dict(_warm_state))
        elif path == "/api/logs/playback":
            self._send_json(200, _tail_lines(config.PLAYBACK_LOG))
        elif path == "/api/cache-root":
            self._send_json(200, {
                "cache_root": config.CACHE_ROOT,
                "problem": config.cache_root_problem(),
                "locked": bool(os.environ.get("SPINCYCLE_CACHE_ROOT")),
                "playback_mode": config.PLAYBACK_MODE,
            })
        else:
            self._send_html(404, "<h1>Not found</h1>")

    def do_POST(self):
        route = self._session_route()
        if route is not None:
            name, action = route
            if name is None:
                if self._require_session_manager():
                    self._handle_session_create()
                return
            if action in ("genre", "era", "skip", "stop", "queue-next", "video-ended", "close"):
                self._handle_session_action(name, action)
                return
            self._send_html(404, "<h1>Not found</h1>")
            return

        track_route = self._library_track_route()
        if track_route is not None:
            self._dispatch_library_track_post(track_route)
            return

        path = self.path_no_query
        if path == "/upload":
            self._handle_upload()
        elif path == "/upload-append":
            self._handle_upload_append()
        elif path == "/warm-cache":
            self._handle_warm_cache()
        elif path == "/api/genre":
            self._handle_select("genre")
        elif path == "/api/era":
            self._handle_select("era")
        elif path == "/api/skip":
            self._handle_transport(self.controller.skip if self.controller else None)
        elif path == "/api/stop":
            self._handle_transport(self.controller.stop if self.controller else None)
        elif path == "/api/queue-next":
            if self._require_controller():
                if self._apply_queue_next(self.controller):
                    self._send_json(200, self.controller.status())
        elif path == "/api/cache-root":
            self._handle_set_cache_root()
        else:
            self._send_html(404, "<h1>Not found</h1>")

    def _require_controller(self):
        if self.controller is None:
            self._send_json(503, {"error": "no playback controller running"})
            return False
        return True

    def _require_session_manager(self):
        if self.session_manager is None:
            self._send_json(503, {"error": "no session manager running"})
            return False
        return True

    # -- sessions (web-mode multi-session support) ------------------------

    def _session_route(self):
        """Parse /api/sessions[/<name>/<action>] into (name, action), or
        (None, None) for the bare /api/sessions collection route. Returns
        None if this path isn't a sessions route at all, so callers fall
        through to the rest of do_GET/do_POST unchanged."""
        parts = self.path_no_query.strip("/").split("/")
        if parts == ["api", "sessions"]:
            return (None, None)
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "sessions":
            return (parts[2], parts[3])
        return None

    def _sessions_status_list(self):
        return [{"name": name, **controller.status()} for name, controller in self.session_manager.list()]

    def _handle_session_status(self, name):
        if not self._require_session_manager():
            return
        controller = self.session_manager.get(name)
        if controller is None:
            self._send_json(404, {"error": f"no such session: {name}"})
            return
        self._send_json(200, {"name": name, **controller.status()})

    def _handle_session_tracks(self, name):
        if not self._require_session_manager():
            return
        controller = self.session_manager.get(name)
        if controller is None:
            self._send_json(404, {"error": f"no such session: {name}"})
            return
        self._send_json(200, {"name": name, **controller.track_list()})

    def _handle_session_create(self):
        name, controller = self.session_manager.create()
        self._send_json(200, {"name": name, **controller.status()})

    def _handle_session_action(self, name, action):
        if not self._require_session_manager():
            return
        if action == "close":
            if self.session_manager.get(name) is None:
                self._send_json(404, {"error": f"no such session: {name}"})
                return
            self.session_manager.close(name)
            self._send_json(200, {"closed": name})
            return

        controller = self.session_manager.get(name)
        if controller is None:
            self._send_json(404, {"error": f"no such session: {name}"})
            return

        if action in ("genre", "era"):
            try:
                payload = self._read_json_body()
            except (ValueError, UnicodeDecodeError) as e:
                self._send_json(400, {"error": str(e)})
                return
            if action == "genre":
                controller.set_genre(payload.get("genre"))
            else:
                controller.set_era(payload.get("era"))
        elif action == "skip":
            controller.skip()
        elif action == "stop":
            controller.stop()
        elif action == "queue-next":
            if not self._apply_queue_next(controller):
                return
        elif action == "video-ended":
            controller.player.mark_ended()

        self._send_json(200, {"name": name, **controller.status()})

    def _apply_queue_next(self, controller):
        """Reads {url} from the request body and calls
        controller.queue_next(). Sends the error response itself and
        returns False on failure; on success returns True and leaves the
        success response to the caller (console vs. session routes shape
        it differently)."""
        try:
            payload = self._read_json_body()
        except (ValueError, UnicodeDecodeError) as e:
            self._send_json(400, {"error": str(e)})
            return False
        try:
            controller.queue_next(payload.get("url"))
        except ValueError as e:
            self._send_json(400, {"error": str(e)})
            return False
        return True

    def _handle_transport(self, action):
        if not self._require_controller():
            return
        action()
        self._send_json(200, self.controller.status())

    # -- static files ------------------------------------------------------

    def _serve_static(self, path):
        file_path, content_type = _STATIC_FILES[path]
        try:
            with open(file_path, "rb") as f:
                body = f.read()
        except OSError:
            self._send_html(404, "<h1>Not found</h1>")
            return
        self._send_bytes(200, body, content_type)

    # -- video streaming (web-mode browser player) ------------------------

    _CHUNK_SIZE = 1024 * 1024

    def _serve_video(self, filename):
        """Serve a cached video file from config.VIDEO_DIR by its flat
        <id>.mp4 filename (see video_cache.py -- no subdirectories, so
        rejecting any '/' or '..' is enough to keep this inside
        VIDEO_DIR). Unlike _serve_static's _send_bytes (which reads the
        whole file into memory -- fine for style.css, wrong for a
        multi-hundred-MB video), this streams in chunks and supports HTTP
        Range requests, which browsers commonly need for <video> seeking."""
        if not filename or "/" in filename or ".." in filename or filename != os.path.basename(filename):
            self._send_html(400, "<h1>Invalid filename</h1>")
            return
        file_path = os.path.join(config.VIDEO_DIR, filename)
        real_dir = os.path.realpath(config.VIDEO_DIR)
        real_path = os.path.realpath(file_path)
        if not real_path.startswith(real_dir + os.sep):
            self._send_html(400, "<h1>Invalid filename</h1>")
            return
        try:
            size = os.path.getsize(real_path)
        except OSError:
            self._send_html(404, "<h1>Not found</h1>")
            return
        self._send_file_range(real_path, size, "video/mp4")

    def _send_file_range(self, path, file_size, content_type):
        start, end, status = 0, file_size - 1, 200
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            try:
                range_spec = rng[len("bytes="):]
                start_str, end_str = range_spec.split("-", 1)
                start = int(start_str) if start_str else 0
                end = min(int(end_str), file_size - 1) if end_str else file_size - 1
                status = 206
            except ValueError:
                start, end, status = 0, file_size - 1, 200

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.end_headers()

        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(self._CHUNK_SIZE, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return  # client closed the connection (tab closed, seeked away) -- not an error
                remaining -= len(chunk)

    def _library_status(self):
        if not os.path.exists(config.LIBRARY_DB):
            return {"exists": False}
        stat = os.stat(config.LIBRARY_DB)
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        track_count = len(library.list_tracks(config.LIBRARY_DB))
        return {"exists": True, "size": stat.st_size, "mtime": mtime, "track_count": track_count}

    def _handle_download_csv(self):
        rows = library.export_csv_rows(config.LIBRARY_DB)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=library.CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
        self._send_bytes(
            200,
            buf.getvalue().encode("utf-8"),
            "text/csv; charset=utf-8",
            extra_headers={"Content-Disposition": 'attachment; filename="library.csv"'},
        )

    # -- playback selection ------------------------------------------------

    def _handle_select(self, field):
        if not self._require_controller():
            return
        try:
            payload = self._read_json_body()
        except (ValueError, UnicodeDecodeError) as e:
            self._send_json(400, {"error": str(e)})
            return
        value = payload.get(field)
        if field == "genre":
            self.controller.set_genre(value)
        else:
            self.controller.set_era(value)
        self._send_json(200, self.controller.status())

    def _handle_set_cache_root(self):
        try:
            payload = self._read_json_body()
        except (ValueError, UnicodeDecodeError) as e:
            self._send_json(400, {"error": str(e)})
            return
        path = (payload.get("cache_root") or "").strip()
        if not path:
            self._send_json(400, {"error": "cache_root must not be empty"})
            return
        try:
            config.set_cache_root(path)
        except RuntimeError as e:
            self._send_json(400, {"error": str(e)})
            return
        except OSError as e:
            self._send_json(400, {"error": f"Can't use that path: {e}"})
            return
        self._send_json(200, {"cache_root": config.CACHE_ROOT})

    # -- library tracks (CRUD, backing the Library panel's table) --------

    def _library_track_route(self):
        """Parse /api/library-tracks[/<id>/<action>] into (id, action); or
        (None, None) for the bare collection route (POST = add a track);
        or (None, "search")/(None, "bulk-delete") for those two id-less
        sub-routes. Returns None if this path isn't a library-tracks route
        at all, so do_POST falls through to its other routes unchanged --
        mirrors _session_route()'s shape."""
        parts = self.path_no_query.strip("/").split("/")
        if parts == ["api", "library-tracks"]:
            return (None, None)
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "library-tracks":
            return (None, parts[2])
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "library-tracks":
            return (parts[2], parts[3])
        return None

    def _dispatch_library_track_post(self, route):
        track_id, action = route
        if track_id is None and action is None:
            self._handle_library_track_add()
        elif track_id is None and action == "search":
            self._handle_library_search()
        elif track_id is None and action == "bulk-delete":
            self._handle_library_bulk_delete()
        elif track_id is not None and action == "update":
            self._handle_library_track_update(track_id)
        elif track_id is not None and action == "delete":
            self._handle_library_track_delete(track_id)
        else:
            self._send_html(404, "<h1>Not found</h1>")

    def _cache_status_for(self, track):
        if video_cache.get_cached_path(track["url"]):
            return "cached"
        if track["cache_error"]:
            return "failed"
        return "not_cached"

    def _list_library_tracks(self):
        tracks = library.list_tracks(config.LIBRARY_DB)
        for track in tracks:
            track["cache_status"] = self._cache_status_for(track)
        return tracks

    def _handle_library_track_add(self):
        try:
            payload = self._read_json_body()
        except (ValueError, UnicodeDecodeError) as e:
            self._send_json(400, {"error": str(e)})
            return

        with _library_lock:
            self._backup_library_db()
            try:
                track_id = library.add_track(
                    config.LIBRARY_DB,
                    payload.get("artist", ""), payload.get("song", ""),
                    payload.get("genre", ""), payload.get("era", ""), payload.get("url", ""),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._reload_library_after_edit()
            track = library.get_track(config.LIBRARY_DB, track_id)

        track["cache_status"] = self._cache_status_for(track)
        self._send_json(200, track)

    def _handle_library_track_update(self, track_id_str):
        try:
            track_id = int(track_id_str)
        except ValueError:
            self._send_json(400, {"error": "invalid track id"})
            return
        try:
            payload = self._read_json_body()
        except (ValueError, UnicodeDecodeError) as e:
            self._send_json(400, {"error": str(e)})
            return

        with _library_lock:
            self._backup_library_db()
            try:
                found = library.update_track(
                    config.LIBRARY_DB, track_id,
                    payload.get("artist", ""), payload.get("song", ""),
                    payload.get("genre", ""), payload.get("era", ""), payload.get("url", ""),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            if not found:
                self._send_json(404, {"error": f"no track with id {track_id}"})
                return
            self._reload_library_after_edit()
            track = library.get_track(config.LIBRARY_DB, track_id)

        track["cache_status"] = self._cache_status_for(track)
        self._send_json(200, track)

    def _handle_library_track_delete(self, track_id_str):
        try:
            track_id = int(track_id_str)
        except ValueError:
            self._send_json(400, {"error": "invalid track id"})
            return

        with _library_lock:
            self._backup_library_db()
            found = library.delete_track(config.LIBRARY_DB, track_id)
            if not found:
                self._send_json(404, {"error": f"no track with id {track_id}"})
                return
            self._reload_library_after_edit()
            video_cache.prune(library.load_library(config.LIBRARY_DB))

        self._send_json(200, {"deleted": track_id})

    def _handle_library_bulk_delete(self):
        try:
            payload = self._read_json_body()
        except (ValueError, UnicodeDecodeError) as e:
            self._send_json(400, {"error": str(e)})
            return
        try:
            ids = [int(i) for i in (payload.get("ids") or [])]
        except (TypeError, ValueError):
            self._send_json(400, {"error": "ids must be a list of integers"})
            return

        with _library_lock:
            self._backup_library_db()
            deleted = library.delete_tracks(config.LIBRARY_DB, ids)
            self._reload_library_after_edit()
            video_cache.prune(library.load_library(config.LIBRARY_DB))

        self._send_json(200, {"deleted": deleted})

    def _handle_library_search(self):
        try:
            payload = self._read_json_body()
        except (ValueError, UnicodeDecodeError) as e:
            self._send_json(400, {"error": str(e)})
            return
        artist = (payload.get("artist") or "").strip()
        song = (payload.get("song") or "").strip()
        if not artist or not song:
            self._send_json(400, {"error": "artist and song are required"})
            return
        try:
            result = video_cache.search_track(artist, song)
        except Exception as e:
            # YouTube search failures aren't an enumerable set (network,
            # extraction, no-results, rate limiting) -- log and surface,
            # don't crash the request per this repo's usual convention.
            self._send_json(502, {"error": f"YouTube search failed: {e}"})
            return
        self._send_json(200, result)

    # -- library upload / cache warming -------------------------------

    def _handle_upload(self):
        self._handle_import_upload(mode="replace")

    def _handle_upload_append(self):
        self._handle_import_upload(mode="append")

    def _handle_import_upload(self, mode):
        length = int(self.headers.get("Content-Length", 0))
        if length > _MAX_UPLOAD_BYTES:
            self.close_connection = True
            self._send_html(413, f"Upload too large ({length} bytes, max {_MAX_UPLOAD_BYTES // (1024 * 1024)} MiB)")
            return
        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")

        tmp_path = config.LIBRARY_DB + ".upload.tmp.csv"
        try:
            file_bytes = parse_multipart_file(content_type, body)
            with open(tmp_path, "wb") as f:
                f.write(file_bytes)
        except ValueError as e:
            self._send_html(400, f"Upload rejected: {html.escape(str(e))}")
            return

        with _library_lock:
            self._backup_library_db()
            try:
                library.import_csv(config.LIBRARY_DB, tmp_path, mode=mode)
            except ValueError as e:
                os.remove(tmp_path)
                self._send_html(400, f"Upload rejected: {html.escape(str(e))}")
                return
            os.remove(tmp_path)

            self._reload_library_after_edit()

            lib = library.load_library(config.LIBRARY_DB)
            # Only a replace can orphan cached videos (append only adds
            # rows) -- skip the whole-cache-index walk when it can't
            # possibly find anything to prune.
            removed = video_cache.prune(lib) if mode == "replace" else []

        genres = len(lib)
        eras = sum(len(e) for e in lib.values())
        tracks = len(library.all_tracks(lib))
        verb = "replaced" if mode == "replace" else "appended to"
        message = f"Upload accepted: library {verb}. Now {genres} genre(s), {eras} genre/era combination(s), {tracks} track(s)."
        if removed:
            message += f" Removed {len(removed)} cached video(s) no longer in the library."
        self._send_html(200, message)

    def _handle_warm_cache(self):
        start_background_warm_cache()

        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def _backup_library_db(self):
        if os.path.exists(config.LIBRARY_DB):
            shutil.copy2(config.LIBRARY_DB, config.LIBRARY_DB + ".bak")

    def _reload_library_after_edit(self):
        if self.controller is not None:
            self.controller.reload_library()

    def log_message(self, fmt, *args):
        print(f"[library_server] {self.address_string()} - {fmt % args}")


def run_server(host=config.LIBRARY_SERVER_HOST, port=config.LIBRARY_SERVER_PORT, controller=None, session_manager=None):
    """Bind and serve forever. Raises OSError if the port can't be bound
    (e.g. permission denied on a privileged port, or already in use) --
    callers that don't want that to be fatal (main.py running this in a
    background thread) should catch it themselves.

    `controller`, if given, is a SpinCycleController used to serve the
    genre/era/skip/stop API routes; without one those routes reply 503
    (library management routes -- upload, warm-cache, download -- work
    either way). `session_manager`, if given, is a SessionManager (web
    mode only) serving the /api/sessions family of routes instead --
    main.py passes exactly one of the two, never both.

    A bad CACHE_ROOT (missing drive, permission denied) is deliberately
    *not* fatal here -- it's only fixable from this same web page's
    Settings panel, so a broken cache path must never stop the page from
    coming up."""
    problem = config.cache_root_problem()
    if problem:
        print(f"[library_server] Warning: cache folder {config.CACHE_ROOT} isn't usable ({problem}).")
    server = ThreadingHTTPServer((host, port), Handler)
    server.controller = controller
    server.session_manager = session_manager
    print(f"Serving on http://{host}:{port} (Ctrl+C to stop)")
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=config.LIBRARY_SERVER_HOST)
    parser.add_argument("--port", type=int, default=config.LIBRARY_SERVER_PORT)
    args = parser.parse_args()

    try:
        run_server(args.host, args.port)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

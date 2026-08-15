"""
Session management for web-mode deployments (config.PLAYBACK_MODE ==
"web"). Unlike the console/Pi target -- one physical device, one viewer,
one SpinCycleController for the app's whole lifetime -- a container-hosted
web deployment can have several people picking different genre/eras and
playing different videos in different browser tabs at once. SessionManager
holds one independent SpinCycleController per session, keyed by a random
adjective-animal name (e.g. "clever-otter") that doubles as the session's
id -- simpler than a separate uuid, and uniqueness is already required for
the web remote's session picker to be usable.

Not used at all in console mode -- main.py wires up a single
SpinCycleController directly there, exactly as before.
"""
import random
import threading

from controller import SpinCycleController

_ADJECTIVES = [
    "clever", "quiet", "brave", "sunny", "lucky", "gentle", "swift", "bold",
    "calm", "eager", "jolly", "kind", "lively", "mighty", "nimble", "proud",
    "silly", "spry", "witty", "zesty", "breezy", "cheerful", "cosmic",
    "curious", "dapper", "dizzy", "electric", "frosty", "golden", "humble",
    "merry", "plucky", "rowdy", "scrappy", "shiny", "sly", "snappy",
    "sparkly", "vivid", "wild",
]
_ANIMALS = [
    "otter", "falcon", "badger", "panda", "heron", "lynx", "gecko", "moose",
    "raven", "walrus", "beaver", "cobra", "dingo", "ferret", "gibbon",
    "hedgehog", "ibex", "jackal", "koala", "loris", "marmot", "newt",
    "ocelot", "puffin", "quokka", "seal", "tapir", "urchin", "vole",
    "weasel", "yak", "zebra", "bison", "cormorant", "dolphin", "egret",
    "flamingo", "gopher", "heron", "impala",
]


class SessionManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions = {}  # name -> SpinCycleController

    def create(self, initial_library=None, playlist_id=None, playlist_name=None):
        with self._lock:
            name = self._unique_name_locked()
            controller = SpinCycleController(
                initial_library=initial_library, playlist_id=playlist_id, playlist_name=playlist_name,
            )
            self._sessions[name] = controller
            return name, controller

    def list(self):
        with self._lock:
            return list(self._sessions.items())

    def get(self, name):
        with self._lock:
            return self._sessions.get(name)

    def close(self, name):
        with self._lock:
            controller = self._sessions.pop(name, None)
        if controller is not None:
            # close() (not stop()) also marks the controller permanently
            # closed, so a set_genre()/set_era() call that grabbed this
            # controller via get() just before the pop above can't spin up
            # a new play thread we'd no longer be able to find or stop.
            controller.close()

    def _unique_name_locked(self):
        while True:
            name = f"{random.choice(_ADJECTIVES)}-{random.choice(_ANIMALS)}"
            if name not in self._sessions:
                return name

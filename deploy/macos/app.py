#!/usr/bin/env python3
"""
Spin Cycle - macOS app wrapper.

A real windowed macOS app -- Dock icon, bounces on launch, stays in the
Dock while running, standard Application menu with Cmd-Q -- around the
same app/ codebase the container target runs in web mode
(SPINCYCLE_PLAYBACK_MODE=web -- no mpv, no DRM/ALSA; decoding happens
client-side). The window is a WKWebView pointed at the local web remote
(http://localhost:8080/ by default), so this is a thin native shell, not
a reimplementation -- all the genre/era/session/DJ logic still lives in
the same web/ JS the browser target uses. Other devices on the LAN can
still reach the same server directly (see config.LIBRARY_SERVER_HOST),
same as the container target -- the window is just this Mac's own client.

Two ways to run this file:
  - Packaged: setup.py's py2app build bundles app/ into Contents/Resources
    (see setup.py's `resources` option) and this becomes the app's entry
    point (Contents/MacOS/app), launched by double-clicking the .app in
    Finder.
  - From source (dev loop, faster than a full py2app build): `python3
    deploy/macos/app.py` after `pip install -r requirements.txt -r
    ../../app/requirements.txt`. _app_source_dir() below falls back to the
    sibling ../../app directory when it's not running from inside a
    bundle.

Env vars/ports are set here, before importing anything from app/, because
config.py reads them at import time (module-level), the same pattern
deploy/raspberrypi/install.sh and deploy/container rely on -- see
config.py's CACHE_ROOT/CONFIG_DIR/LIBRARY_SERVER_PORT comments.
"""
import os
import subprocess
import sys
import threading
from pathlib import Path

from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSMenu,
    NSMenuItem,
    NSObject,
    NSOKButton,
    NSOpenPanel,
    NSScreen,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeRect, NSURL, NSURLRequest
from PyObjCTools import AppHelper
from WebKit import WKWebView

PORT = 8080
WINDOW_SIZE = (1100, 750)
WINDOW_MIN_SIZE = (760, 520)
PLAYER_WINDOW_SIZE = (960, 620)

# A Dock/Finder-launched app inherits launchd's bare default PATH, not the
# interactive shell's -- it never sees a `brew shellenv`-style PATH from
# .zprofile. Without this, yt-dlp reports "ffmpeg is not installed" even
# right after `brew install ffmpeg`, since Homebrew lives in
# /opt/homebrew/bin (Apple Silicon) or /usr/local/bin (Intel), neither of
# which is on that default PATH. Prepending both covers either Mac.
_HOMEBREW_PATHS = ("/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", "/usr/local/sbin")

APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "Spin Cycle"
CACHE_DIR = APP_SUPPORT_DIR / "cache"
CONFIG_DIR = APP_SUPPORT_DIR / "config"


def _app_source_dir() -> str:
    """
    Locate the bundled app/ codebase: Contents/Resources/app next to this
    script's Contents/MacOS/app when packaged (see setup.py), or the
    sibling ../../app directory when running from a source checkout.
    """
    bundled = Path(sys.argv[0]).resolve().parent.parent / "Resources" / "app"
    if bundled.is_dir():
        return str(bundled)
    return str(Path(__file__).resolve().parent.parent.parent / "app")


def _seed_config(app_dir: str) -> None:
    """
    Copy the starter config/library.csv into Application Support on first
    launch only -- never overwrites an existing one, so a real library.csv
    already there (either a pre-SQLite install's live file, or the
    .pre-migration.bak-style artifact left after upgrading) survives an app
    update (a rebuilt .app's bundled starter library.csv is replaced, but
    Application Support isn't touched by rebuilding). This seeded/existing
    CSV is only ever a one-time migration source -- library._ensure_db()
    imports it into library.db (the live store) the first time anything in
    the app touches the library, and never writes to the CSV again.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    dest = CONFIG_DIR / "library.csv"
    if dest.exists():
        return
    src = Path(app_dir) / "config" / "library.csv"
    if src.exists():
        dest.write_bytes(src.read_bytes())


def _exclude_cache_from_spotlight() -> None:
    """
    Drop an empty `.metadata_never_index` file at the root of CACHE_DIR --
    Spotlight's documented sentinel for "don't index anything under here"
    (see `man mdimport`). Without it, mdworker tries to index every
    downloaded video as it lands, which is real, measurable CPU/disk
    contention with warm-cache's own downloads that a k3s/container
    deployment never has to compete with (no Spotlight on Linux) -- and
    Spotlight indexing video *content* (thumbnails/metadata extraction)
    isn't worth the cost even though the filenames themselves are now
    human-readable (<artist>-<song>.mp4).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    sentinel = CACHE_DIR / ".metadata_never_index"
    if not sentinel.exists():
        sentinel.touch()


def _local_url() -> str:
    return f"http://localhost:{PORT}/"


def _start_spincycle(app_dir: str) -> bool:
    """
    Set up env vars + start library_server.py in a background thread.
    Mirrors app/main.py's setup (minus the console splash and the
    blocking wait loop, which don't apply here) so this stays the same
    web-mode startup path the container target uses. Returns False if a
    hard dependency is missing (caller should show an alert and quit).
    """
    os.environ["SPINCYCLE_PLAYBACK_MODE"] = "web"
    os.environ["SPINCYCLE_CACHE_ROOT"] = str(CACHE_DIR)
    os.environ["SPINCYCLE_CONFIG_DIR"] = str(CONFIG_DIR)
    os.environ["SPINCYCLE_SERVER_PORT"] = str(PORT)
    os.environ["PATH"] = os.pathsep.join([*_HOMEBREW_PATHS, os.environ.get("PATH", "")])
    _seed_config(app_dir)
    _exclude_cache_from_spotlight()

    sys.path.insert(0, app_dir)
    import config
    import video_cache
    import library_server
    from sessions import SessionManager

    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return False

    problem = config.cache_root_problem()
    if problem:
        print(f"[spincycle] Warning: cache folder {config.CACHE_ROOT} isn't usable ({problem}).")
    else:
        video_cache.clear_incoming()

    session_manager = SessionManager()
    library_server.start_background_warm_cache()

    def _run():
        try:
            library_server.run_server(session_manager=session_manager)
        except OSError as e:
            print(f"[spincycle] Could not start web remote: {e}")

    threading.Thread(target=_run, daemon=True).start()
    return True


class AppDelegate(NSObject):
    def applicationDidFinishLaunching_(self, notification):
        app_dir = _app_source_dir()
        if not _start_spincycle(app_dir):
            alert = NSAlert.alloc().init()
            alert.setMessageText_("Spin Cycle can't start")
            alert.setInformativeText_(
                "yt-dlp isn't installed in this app's bundled environment. "
                "Rebuild via deploy/macos/build.sh."
            )
            alert.runModal()
            NSApplication.sharedApplication().terminate_(self)
            return
        self._build_menu()
        self.window = None
        self._player_windows = []
        self._show_window()

    def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
        # Closing the window is not quitting the app -- same convention as
        # Mail/Preview/etc: the Dock icon (and the local web server, still
        # reachable by other LAN devices) stays up until Cmd-Q/Quit.
        return False

    def applicationShouldHandleReopen_hasVisibleWindows_(self, sender, has_visible_windows):
        # Standard Mac behavior: clicking a running app's Dock icon again
        # after its last window was closed should bring a window back.
        if not has_visible_windows:
            self._show_window()
        return True

    def _show_window(self):
        if self.window is not None:
            self.window.makeKeyAndOrderFront_(None)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            return

        screen = NSScreen.mainScreen().frame()
        width, height = WINDOW_SIZE
        x = (screen.size.width - width) / 2
        y = (screen.size.height - height) / 2
        rect = NSMakeRect(x, y, width, height)
        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskResizable
            | NSWindowStyleMaskMiniaturizable
        )
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False
        )
        window.setTitle_("Spin Cycle")
        window.setMinSize_(WINDOW_MIN_SIZE)
        # Not released on close (the default) -- we keep our own reference
        # in self.window and reuse/re-show it on the next Dock click
        # instead of ever recreating it.
        window.setReleasedWhenClosed_(False)

        webview = WKWebView.alloc().initWithFrame_(rect)
        # web/app.js's "Launch Player" button opens the player via
        # `window.open(...)` (see app/web/app.js) so it lands in its own
        # tab in a real browser, leaving the remote controls usable in the
        # original tab. A bare WKWebView has no default handler for
        # window.open() at all -- it's silently a no-op without a
        # WKUIDelegate -- which is exactly why clicking Launch Player did
        # nothing. webView_createWebViewWithConfiguration_... below is
        # that delegate's required handler, opening a second native
        # window instead of a second tab (WKWebView has no tab concept),
        # which gets the same "controls in one window, player in another"
        # result.
        webview.setUIDelegate_(self)
        # Lets Safari's Develop menu attach a real Web Inspector to this
        # webview (Develop -> <this Mac> -> Spin Cycle) -- needed while
        # this target is new/still-being-debugged; WKWebView content is
        # otherwise a black box from outside the app itself.
        webview.setInspectable_(True)
        webview.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(_local_url())))
        window.setContentView_(webview)

        window.makeKeyAndOrderFront_(None)
        self.window = window
        self.webview = webview

    def webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(
        self, webView, configuration, navigationAction, windowFeatures
    ):
        """
        WKUIDelegate hook for `window.open()`. Returning a new WKWebView
        (built with the *same* configuration WebKit hands us, not a fresh
        one) tells WebKit to continue the pending navigation into that
        view itself -- we shouldn't also call loadRequest ourselves here.
        """
        screen = NSScreen.mainScreen().frame()
        width, height = PLAYER_WINDOW_SIZE
        x = (screen.size.width - width) / 2
        y = (screen.size.height - height) / 2
        rect = NSMakeRect(x, y, width, height)
        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskResizable
            | NSWindowStyleMaskMiniaturizable
        )
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False
        )
        window.setTitle_("Spin Cycle Player")
        window.setReleasedWhenClosed_(False)

        player_webview = WKWebView.alloc().initWithFrame_configuration_(rect, configuration)
        window.setContentView_(player_webview)
        window.makeKeyAndOrderFront_(None)

        # Keep a strong reference -- nothing else holds onto this window/
        # webview pair otherwise, and Python would garbage-collect them
        # (and the visible window with them) as soon as this method
        # returns.
        self._player_windows.append((window, player_webview))
        return player_webview

    def webView_runOpenPanelWithParameters_initiatedByFrame_completionHandler_(
        self, webView, parameters, frame, completionHandler
    ):
        """
        WKUIDelegate hook for `<input type="file">` (the Library panel's
        CSV import, see app/web/index.html) -- same story as
        window.open() above: WKWebView has no built-in file picker of its
        own, so clicking "Choose File" does nothing at all without this.

        Presented as a sheet on the webview's own window with an async
        completion handler (Apple's documented pattern for this delegate
        method) rather than a plain app-modal `runModal()` -- the latter
        shows a panel that looks like it works (you can pick a file and
        it dismisses) but doesn't reliably hand the selection back to
        WebKit's web process, which reads as the picker "working" while
        the page's <input> stays empty and the subsequent form submit
        silently fails HTML5 required-field validation with no visible
        error (WKWebView doesn't render the usual validation bubble).
        """
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(False)
        panel.setAllowsMultipleSelection_(parameters.allowsMultipleSelection())

        def _finish(result):
            completionHandler(panel.URLs() if result == NSOKButton else None)

        window = webView.window()
        if window is not None:
            panel.beginSheetModalForWindow_completionHandler_(window, _finish)
        else:
            _finish(panel.runModal())

    def webView_runJavaScriptAlertPanelWithMessage_initiatedByFrame_completionHandler_(
        self, webView, message, frame, completionHandler
    ):
        """
        WKUIDelegate hook for JS `alert()` (web/app.js uses it for error
        messages, e.g. a failed queue-next or cache-failure edit -- see
        its `alert(result.error)` calls). Same story as the other two
        fixes: WKWebView has no default JS-dialog UI, so without this,
        `alert()` is just silently a no-op -- no error ever visible, not
        even a hang.
        """
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Spin Cycle")
        alert.setInformativeText_(str(message))
        window = webView.window()
        if window is not None:
            alert.beginSheetModalForWindow_completionHandler_(window, lambda _resp: completionHandler())
        else:
            alert.runModal()
            completionHandler()

    def webView_runJavaScriptConfirmPanelWithMessage_initiatedByFrame_completionHandler_(
        self, webView, message, frame, completionHandler
    ):
        """
        WKUIDelegate hook for JS `confirm()` -- this is the actual bug
        behind "Upload replacement does nothing": app.js's submit handler
        opens with `if (!confirm(...)) return;` (also used for the DJ
        panel's remove-song confirmation). Unhandled, WKWebView's default
        response to an unimplemented confirm() is to resolve it `false`
        immediately and silently -- no dialog ever appears -- which hits
        that early `return` and makes the whole button look dead.
        """
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Spin Cycle")
        alert.setInformativeText_(str(message))
        alert.addButtonWithTitle_("OK")
        alert.addButtonWithTitle_("Cancel")
        window = webView.window()
        if window is not None:
            alert.beginSheetModalForWindow_completionHandler_(
                window, lambda resp: completionHandler(resp == NSAlertFirstButtonReturn)
            )
        else:
            completionHandler(alert.runModal() == NSAlertFirstButtonReturn)

    def openInBrowser_(self, sender):
        import webbrowser
        webbrowser.open(_local_url())

    def revealCache_(self, sender):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(CACHE_DIR)], check=False)

    def revealLibrary_(self, sender):
        # library.db is the live store (see library.py) -- it exists by the
        # time this menu item is clickable, since main.py's startup always
        # loads the library at least once before the app finishes launching.
        subprocess.run(["open", "-R", str(CONFIG_DIR / "library.db")], check=False)

    def _build_menu(self):
        """
        A regular (non-UIElement) app is expected to have a standard top
        menu bar -- AppKit doesn't build one for free, so this does it by
        hand: the bold Application menu (macOS convention: Quit lives
        here, bound to Cmd-Q via the target-less `terminate:` action,
        which the responder chain routes to NSApplication automatically)
        plus a small File menu for this app's few real actions.
        """
        main_menu = NSMenu.alloc().init()

        app_menu_item = NSMenuItem.alloc().init()
        main_menu.addItem_(app_menu_item)
        app_menu = NSMenu.alloc().init()
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit Spin Cycle", "terminate:", "q"
        )
        app_menu.addItem_(quit_item)
        app_menu_item.setSubmenu_(app_menu)

        file_menu_item = NSMenuItem.alloc().init()
        main_menu.addItem_(file_menu_item)
        file_menu = NSMenu.alloc().initWithTitle_("File")
        for title, action, key in [
            ("Open in Browser", "openInBrowser:", "b"),
            ("Reveal Video Cache in Finder", "revealCache:", ""),
            ("Reveal Library File in Finder", "revealLibrary:", ""),
        ]:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
            item.setTarget_(self)
            file_menu.addItem_(item)
        file_menu_item.setSubmenu_(file_menu)

        NSApplication.sharedApplication().setMainMenu_(main_menu)


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.activateIgnoringOtherApps_(True)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()

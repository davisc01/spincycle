(function () {
  const genreSelect = document.getElementById("genre-select");
  const eraSelect = document.getElementById("era-select");
  const statusMessage = document.getElementById("status-message");
  const skipBtn = document.getElementById("skip-btn");
  const stopBtn = document.getElementById("stop-btn");
  const djBtn = document.getElementById("dj-btn");
  const djPanel = document.getElementById("dj-panel");
  const djPanelStatus = document.getElementById("dj-panel-status");
  const songList = document.getElementById("song-list");
  const upNextLine = document.getElementById("up-next-line");
  const launchPlayerBtn = document.getElementById("launch-player-btn");
  const backToSessions = document.getElementById("back-to-sessions");

  const sessionPicker = document.getElementById("session-picker");
  const sessionList = document.getElementById("session-list");
  const newSessionBtn = document.getElementById("new-session-btn");
  const remote = document.getElementById("remote");

  const settingsToggle = document.getElementById("settings-toggle");
  const settingsPanel = document.getElementById("settings");
  const libraryStatus = document.getElementById("library-status");
  const warmStatus = document.getElementById("warm-status");
  const warmCacheBtn = document.getElementById("warm-cache-btn");
  const playbackLog = document.getElementById("playback-log");
  const cacheWarning = document.getElementById("cache-warning");
  const connectionWarning = document.getElementById("connection-warning");
  const emptyLibraryNotice = document.getElementById("empty-library-notice");

  const addTrackBtn = document.getElementById("add-track-btn");
  const importAppendBtn = document.getElementById("import-append-btn");
  const importReplaceBtn = document.getElementById("import-replace-btn");
  const importCsvInput = document.getElementById("import-csv-input");
  const importResult = document.getElementById("import-result");
  const bulkDeleteBtn = document.getElementById("bulk-delete-btn");
  const selectAllTracks = document.getElementById("select-all-tracks");
  const libraryTable = document.getElementById("library-table");
  const libraryTableBody = document.getElementById("library-table-body");
  const librarySortField = document.getElementById("library-sort-field");
  const librarySortDir = document.getElementById("library-sort-dir");

  const trackFormPanel = document.getElementById("track-form-panel");
  const trackFormTitle = document.getElementById("track-form-title");
  const trackForm = document.getElementById("track-form");
  const trackArtist = document.getElementById("track-artist");
  const trackSong = document.getElementById("track-song");
  const trackGenre = document.getElementById("track-genre");
  const trackEra = document.getElementById("track-era");
  const trackUrl = document.getElementById("track-url");
  const trackPreviewBtn = document.getElementById("track-preview-btn");
  const trackSearchBtn = document.getElementById("track-search-btn");
  const trackSearchStatus = document.getElementById("track-search-status");
  const trackCancelBtn = document.getElementById("track-cancel-btn");

  const infoPlaybackMode = document.getElementById("info-playback-mode");
  const infoCacheRoot = document.getElementById("info-cache-root");
  const infoLastWarmRun = document.getElementById("info-last-warm-run");

  let warmPollTimer = null;

  // -- session-aware routing --------------------------------------------
  //
  // Console mode (the Pi target): a single SpinCycleController, no
  // sessions -- the flat /api/<action> routes from before. Web mode (k3s
  // target): one SessionManager holding many independent
  // SpinCycleControllers, so every playback route is scoped under
  // /api/sessions/<name>/<action> instead. See sessions.py/CLAUDE.md.
  // mode/session are set once by init() below and read by actionUrl().

  let mode = null; // "console" | "web"
  let session = null; // current session name, web mode only
  let statusPollTimer = null;

  function actionUrl(action) {
    if (mode === "web") {
      return `/api/sessions/${encodeURIComponent(session)}/${action}`;
    }
    return `/api/${action}`;
  }

  function fillOptions(select, options, selected, placeholder) {
    select.innerHTML = "";
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = placeholder;
    select.appendChild(empty);
    for (const opt of options) {
      const el = document.createElement("option");
      el.value = opt;
      el.textContent = opt;
      select.appendChild(el);
    }
    select.value = selected || "";
  }

  // -- rotary dial controls ---------------------------------------------
  //
  // Mirrors the target hardware's rotary encoders (see CLAUDE.md). The
  // <select> stays the source of truth and accessible fallback -- the
  // dial just drives it via select.value + a dispatched "change" event,
  // so it reuses the existing change listeners below rather than talking
  // to the API directly.
  //
  // The knob spins as a continuous, unbounded rotation (not a bounded
  // needle-in-an-arc gauge) -- each option occupies an equal 360/count
  // degree slice, matching the physical encoder's endless-rotation wrap
  // (Rock -> Pop -> ... -> Anything -> back to Rock). Dragging tracks
  // fluidly frame-by-frame; releasing with velocity coasts with friction
  // and eases into the nearest slice. The <select> (and therefore the
  // API commit + playback restart) only updates once a spin actually
  // settles to rest -- not on every slice crossed mid-drag/mid-coast --
  // so a fast flick doesn't fire a burst of genre/era changes.

  const DIAL_DRAG_PX_PER_STEP = 24;
  const DIAL_FRICTION_PER_FRAME = 0.95; // decay factor per 16.67ms (60fps) frame
  const DIAL_VELOCITY_STOP_THRESHOLD = 0.02; // deg/ms
  const DIAL_MAX_VELOCITY = 6; // deg/ms, clamp on release
  const DIAL_SETTLE_MS = 200;
  const DIAL_FRAME_DT_CLAMP_MS = 48;
  const DIAL_BACKGROUND_GAP_MS = 250; // treat a bigger gap as a backgrounded tab
  const DIAL_VELOCITY_SAMPLE_WINDOW_MS = 120;

  function createDial(select, dialEl, readoutEl) {
    const knob = dialEl.querySelector(".dial-knob");
    const prevBtn = dialEl.querySelector(".dial-step-prev");
    const nextBtn = dialEl.querySelector(".dial-step-next");

    function sliceDeg() {
      const count = select.options.length;
      return count > 0 ? 360 / count : 360;
    }

    function setIndex(newIndex) {
      const count = select.options.length;
      if (count === 0) return;
      const wrapped = ((newIndex % count) + count) % count;
      if (select.selectedIndex === wrapped) return;
      select.selectedIndex = wrapped;
      select.dispatchEvent(new Event("change"));
    }

    let rotation = select.selectedIndex * sliceDeg(); // continuous, unbounded degrees
    let interactionState = "idle"; // idle | dragging | coasting | settling
    let velocity = 0; // deg/ms
    let rafId = null;
    let dragStartY = null;
    let dragStartRotation = 0;
    let dragSliceDeg = 0;
    let moveSamples = []; // trailing window of {t, rotation}, for release velocity
    let lastRenderedNearest = -1;
    let settleFrom = 0;
    let settleTo = 0;
    let settleStart = 0;
    let lastCoastT = null;

    // Updates the visual rotation and the live readout every frame of a
    // drag/coast/settle, without touching the <select>/committing.
    function applyVisual(rotationValue) {
      knob.style.setProperty("--angle", `${rotationValue}deg`);
      const count = select.options.length;
      if (count === 0) return;
      const nearest = Math.round(rotationValue / sliceDeg());
      const wrapped = ((nearest % count) + count) % count;
      if (wrapped !== lastRenderedNearest) {
        lastRenderedNearest = wrapped;
        const opt = select.options[wrapped];
        readoutEl.textContent = opt ? opt.textContent : "";
      }
    }

    function commitSettledIndex() {
      const count = select.options.length;
      if (count === 0) return;
      const s = sliceDeg();
      const nearest = Math.round(rotation / s);
      const wrapped = ((nearest % count) + count) % count;
      setIndex(wrapped);
      // Fold rotation back near the canonical angle (±360) so it doesn't
      // grow unboundedly over a long session of repeated flicks.
      rotation = wrapped * s + Math.round((rotation - wrapped * s) / 360) * 360;
    }

    function beginSettle() {
      const s = sliceDeg();
      const nearest = Math.round(rotation / s);
      settleFrom = rotation;
      settleTo = nearest * s;
      settleStart = performance.now();
      interactionState = "settling";
      rafId = requestAnimationFrame(tick);
    }

    function tick(ts) {
      if (interactionState === "coasting") {
        if (lastCoastT === null) lastCoastT = ts;
        const rawDt = ts - lastCoastT;
        lastCoastT = ts;
        if (rawDt > DIAL_BACKGROUND_GAP_MS) {
          velocity = 0; // tab was backgrounded -- don't fast-forward the spin
        } else {
          const dt = Math.min(rawDt, DIAL_FRAME_DT_CLAMP_MS);
          rotation += velocity * dt;
          velocity *= Math.pow(DIAL_FRICTION_PER_FRAME, dt / 16.6667);
          applyVisual(rotation);
        }
        if (Math.abs(velocity) < DIAL_VELOCITY_STOP_THRESHOLD) {
          beginSettle();
          return;
        }
        rafId = requestAnimationFrame(tick);
        return;
      }
      if (interactionState === "settling") {
        const t = Math.min(1, (ts - settleStart) / DIAL_SETTLE_MS);
        const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
        rotation = settleFrom + (settleTo - settleFrom) * eased;
        applyVisual(rotation);
        if (t < 1) {
          rafId = requestAnimationFrame(tick);
          return;
        }
        rotation = settleTo;
        applyVisual(rotation);
        interactionState = "idle";
        commitSettledIndex();
      }
    }

    function startCoast(v) {
      velocity = v;
      interactionState = "coasting";
      lastCoastT = null;
      rafId = requestAnimationFrame(tick);
    }

    // Used by the prev/next step buttons and mouse wheel -- a short tween
    // through the same easing as a settle, chainable mid-flight (a new
    // click/wheel-tick just re-tweens from wherever the last one got to).
    function tweenToNearestPlusDelta(delta) {
      if (select.options.length <= 1) return;
      cancelAnimationFrame(rafId);
      const s = sliceDeg();
      const nearest = Math.round(rotation / s);
      settleFrom = rotation;
      settleTo = (nearest + delta) * s;
      settleStart = performance.now();
      interactionState = "settling";
      rafId = requestAnimationFrame(tick);
    }

    prevBtn.addEventListener("click", () => tweenToNearestPlusDelta(-1));
    nextBtn.addEventListener("click", () => tweenToNearestPlusDelta(1));

    let wheelAccum = 0;
    knob.addEventListener(
      "wheel",
      (event) => {
        if (select.options.length <= 1) return;
        event.preventDefault();
        wheelAccum += event.deltaY;
        if (Math.abs(wheelAccum) >= 40) {
          tweenToNearestPlusDelta(wheelAccum > 0 ? 1 : -1);
          wheelAccum = 0;
        }
      },
      { passive: false }
    );

    knob.addEventListener("pointerdown", (event) => {
      // Nothing to spin through yet (e.g. era before a genre is picked).
      if (select.options.length <= 1) return;
      cancelAnimationFrame(rafId);
      interactionState = "dragging";
      dragStartY = event.clientY;
      dragStartRotation = rotation; // continue from wherever a coast/settle had gotten to
      dragSliceDeg = sliceDeg();
      moveSamples = [{ t: event.timeStamp, rotation }];
      knob.setPointerCapture(event.pointerId);
      event.preventDefault();
    });

    knob.addEventListener("pointermove", (event) => {
      if (dragStartY === null) return;
      const deltaY = dragStartY - event.clientY;
      rotation = dragStartRotation + deltaY * (dragSliceDeg / DIAL_DRAG_PX_PER_STEP);
      const now = event.timeStamp;
      moveSamples.push({ t: now, rotation });
      while (moveSamples.length > 1 && now - moveSamples[0].t > DIAL_VELOCITY_SAMPLE_WINDOW_MS) {
        moveSamples.shift();
      }
      applyVisual(rotation);
    });

    function computeReleaseVelocity(now) {
      if (moveSamples.length < 2) return 0;
      const last = moveSamples[moveSamples.length - 1];
      if (now - last.t > 60) return 0; // paused before lifting -- not a flick
      const first = moveSamples[0];
      const dt = last.t - first.t;
      if (dt < 4) return 0;
      const v = (last.rotation - first.rotation) / dt;
      return Math.max(-DIAL_MAX_VELOCITY, Math.min(DIAL_MAX_VELOCITY, v));
    }

    function endDrag(event) {
      if (dragStartY === null) return;
      dragStartY = null;
      if (knob.hasPointerCapture(event.pointerId)) {
        knob.releasePointerCapture(event.pointerId);
      }
      startCoast(computeReleaseVelocity(event.timeStamp));
    }
    knob.addEventListener("pointerup", endDrag);
    knob.addEventListener("pointercancel", endDrag);

    function render() {
      const count = select.options.length;
      const usable = count > 1;
      prevBtn.disabled = !usable;
      nextBtn.disabled = !usable;
      // A poll tick rebuilds <option>s and calls render() every ~2s --
      // only resync from the <select> while idle, or an in-progress spin
      // would get snapped back mid-gesture.
      if (interactionState === "idle") {
        rotation = select.selectedIndex * sliceDeg();
        applyVisual(rotation);
      }
    }

    return { render };
  }

  const genreDial = createDial(genreSelect, document.getElementById("genre-dial"), document.getElementById("genre-readout"));
  const eraDial = createDial(eraSelect, document.getElementById("era-dial"), document.getElementById("era-readout"));

  function renderStatus(status) {
    fillOptions(genreSelect, status.genre_options, status.genre, "-- pick a genre --");
    fillOptions(eraSelect, status.era_options, status.era, status.genre ? "-- pick an era --" : "-- pick a genre first --");
    genreDial.render();
    eraDial.render();
    statusMessage.textContent = status.status_message;
    statusMessage.classList.toggle("playing", status.playing);
    stopBtn.disabled = !status.playing;
    skipBtn.disabled = !status.playing;
    djBtn.disabled = !status.genre || !status.era;
    launchPlayerBtn.hidden = mode !== "web";

    if (status.up_next) {
      const t = status.up_next;
      upNextLine.textContent = `Up next: ${t.artist ? `${t.artist} - ${t.song}` : t.url}`;
      upNextLine.hidden = false;
    } else {
      upNextLine.hidden = true;
    }

    if (status.cache_root_problem) {
      cacheWarning.textContent = `Cache folder isn't set up (${status.cache_root_problem}). See Deployment info in Settings for the configured path.`;
      cacheWarning.hidden = false;
    } else {
      cacheWarning.hidden = true;
    }

    // genre_options is always real genres + the "Anything" wildcard (see
    // library.genre_options) -- a length of 1 means there are no real
    // genres at all, i.e. the library is empty or never uploaded.
    emptyLibraryNotice.hidden = status.genre_options.length > 1;
  }

  // A dropped connection (phone loses wifi, server restarts) makes fetch()
  // reject rather than resolve with a bad status -- track that separately
  // so the poll loop can surface it instead of freezing silently on stale
  // state (see player.js's poll(), which already does the same for the
  // player tab).
  let connectionOk = true;
  function setConnectionState(ok) {
    if (ok === connectionOk) return;
    connectionOk = ok;
    connectionWarning.hidden = ok;
  }

  async function fetchStatus() {
    let res;
    try {
      res = await fetch(actionUrl("status"));
    } catch (e) {
      setConnectionState(false);
      return null; // transient network hiccup -- just retry next poll
    }
    setConnectionState(true);
    if (!res.ok) {
      if (mode === "web") {
        // Session probably got closed (e.g. from another tab) -- bounce
        // back to the picker rather than polling a dead session forever.
        showSessionPicker();
      }
      return null;
    }
    const status = await res.json();
    renderStatus(status);
    return status;
  }

  async function postJSON(url, body) {
    let res;
    try {
      res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (e) {
      setConnectionState(false);
      return null; // transient network hiccup -- caller should no-op
    }
    setConnectionState(true);
    return res.json();
  }

  genreSelect.addEventListener("change", async () => {
    const status = await postJSON(actionUrl("genre"), { genre: genreSelect.value || null });
    if (status) renderStatus(status);
  });

  eraSelect.addEventListener("change", async () => {
    const status = await postJSON(actionUrl("era"), { era: eraSelect.value || null });
    if (status) renderStatus(status);
  });

  skipBtn.addEventListener("click", async () => {
    const status = await postJSON(actionUrl("skip"));
    if (status) renderStatus(status);
  });

  stopBtn.addEventListener("click", async () => {
    const status = await postJSON(actionUrl("stop"));
    if (status) renderStatus(status);
  });

  launchPlayerBtn.addEventListener("click", () => {
    window.open(`/player?session=${encodeURIComponent(session)}`, "_blank");
  });

  // -- DJ panel (inline song browser/queue, toggled by the DJ button) ---

  let djOpen = false;

  function openDjPanel() {
    djOpen = true;
    djPanel.hidden = false;
    djBtn.setAttribute("aria-expanded", "true");
    refreshDjPanel();
  }

  function closeDjPanel() {
    djOpen = false;
    djPanel.hidden = true;
    djBtn.setAttribute("aria-expanded", "false");
  }

  djBtn.addEventListener("click", () => {
    if (djOpen) {
      closeDjPanel();
    } else {
      openDjPanel();
    }
  });

  function trackLabel(track) {
    return track.artist ? `${track.artist} - ${track.song}` : track.url;
  }

  function renderDjPanel(data) {
    if (!data.tracks.length) {
      djPanelStatus.textContent = data.genre && data.era
        ? "No tracks in this genre/era."
        : "Pick a genre and era to see songs here.";
      songList.innerHTML = "";
      return;
    }
    djPanelStatus.textContent = "";
    songList.innerHTML = "";
    for (const track of data.tracks) {
      const li = document.createElement("li");
      li.className = "song-item";
      const isPlaying = data.current_track && data.current_track.url === track.url;
      const isQueued = data.queued_track && data.queued_track.url === track.url;
      if (isPlaying) li.classList.add("now-playing");
      if (isQueued) li.classList.add("queued");

      const info = document.createElement("div");
      info.className = "song-info";
      const title = document.createElement("span");
      title.className = "song-title";
      title.textContent = trackLabel(track);
      const meta = document.createElement("span");
      meta.className = "song-meta";
      meta.textContent = `${track.genre} / ${track.era}`;
      info.append(title, meta);
      if (isPlaying || isQueued) {
        const badge = document.createElement("span");
        badge.className = "song-badge";
        badge.textContent = isPlaying ? "Now playing" : "Up next";
        info.append(badge);
      }

      const actions = document.createElement("div");
      actions.className = "song-actions";
      const queueBtn = document.createElement("button");
      queueBtn.type = "button";
      queueBtn.textContent = isQueued ? "Queued" : "Queue";
      queueBtn.disabled = isQueued;
      queueBtn.addEventListener("click", async () => {
        queueBtn.disabled = true;
        const result = await postJSON(actionUrl("queue-next"), { url: track.url });
        if (!result) {
          queueBtn.disabled = false;
          return; // transient network hiccup -- next poll retries
        }
        if (result.error) {
          alert(result.error);
          queueBtn.disabled = false;
          return;
        }
        renderStatus(result);
        refreshDjPanel();
      });
      actions.appendChild(queueBtn);

      li.append(info, actions);
      songList.appendChild(li);
    }
  }

  async function refreshDjPanel() {
    let res;
    try {
      res = await fetch(actionUrl("tracks"));
    } catch (e) {
      return; // transient network hiccup -- just try again next poll
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      djPanelStatus.textContent = body.error || `Error: ${res.status}`;
      songList.innerHTML = "";
      return;
    }
    const data = await res.json();
    renderDjPanel(data);
  }

  async function pollTick() {
    await fetchStatus();
    if (djOpen) refreshDjPanel();
  }

  backToSessions.addEventListener("click", (event) => {
    event.preventDefault();
    showSessionPicker();
  });

  // -- session picker (web mode only) ------------------------------------

  function renderSessionList(sessions) {
    sessionList.innerHTML = "";
    if (!sessions.length) {
      const li = document.createElement("li");
      li.textContent = "(none)";
      sessionList.appendChild(li);
      return;
    }
    for (const s of sessions) {
      const li = document.createElement("li");
      li.className = "session-item";

      const info = document.createElement("div");
      info.className = "session-info";
      const name = document.createElement("span");
      name.className = "session-name";
      name.textContent = s.name;
      const meta = document.createElement("span");
      meta.className = "session-meta";
      meta.textContent = s.playing
        ? s.status_message
        : s.genre || s.era
        ? `${s.genre || "Anything"} / ${s.era || "Anytime"}`
        : "idle";
      info.append(name, meta);

      const actions = document.createElement("div");
      actions.className = "session-actions";
      const selectBtn = document.createElement("button");
      selectBtn.type = "button";
      selectBtn.textContent = "Select";
      selectBtn.addEventListener("click", () => selectSession(s.name));
      const closeBtn = document.createElement("button");
      closeBtn.type = "button";
      closeBtn.className = "close-session-btn";
      closeBtn.textContent = "Close";
      closeBtn.addEventListener("click", () => closeSession(s.name));
      actions.append(selectBtn, closeBtn);

      li.append(info, actions);
      sessionList.appendChild(li);
    }
  }

  async function refreshSessionList() {
    const res = await fetch("/api/sessions");
    const sessions = await res.json();
    renderSessionList(sessions);
  }

  newSessionBtn.addEventListener("click", async () => {
    const created = await postJSON("/api/sessions");
    selectSession(created.name);
  });

  function showSessionPicker() {
    session = null;
    closeDjPanel();
    if (statusPollTimer) {
      clearInterval(statusPollTimer);
      statusPollTimer = null;
    }
    remote.hidden = true;
    sessionPicker.hidden = false;
    history.pushState(null, "", "/");
    refreshSessionList();
  }

  function selectSession(name) {
    session = name;
    closeDjPanel();
    sessionPicker.hidden = true;
    remote.hidden = false;
    backToSessions.hidden = false;
    history.pushState(null, "", `/?session=${encodeURIComponent(name)}`);
    pollTick();
    if (statusPollTimer) clearInterval(statusPollTimer);
    statusPollTimer = setInterval(pollTick, 2000);
  }

  async function closeSession(name) {
    await postJSON(`/api/sessions/${encodeURIComponent(name)}/close`);
    if (session === name) {
      showSessionPicker();
    } else {
      refreshSessionList();
    }
  }

  // -- settings panel ------------------------------------------------

  function openSettings() {
    settingsPanel.hidden = false;
    settingsToggle.setAttribute("aria-expanded", "true");
    refreshSettings();
  }

  settingsToggle.addEventListener("click", () => {
    const isOpen = !settingsPanel.hidden;
    settingsPanel.hidden = isOpen;
    settingsToggle.setAttribute("aria-expanded", String(!isOpen));
    if (!isOpen) {
      refreshSettings();
    }
  });

  cacheWarning.addEventListener("click", openSettings);
  emptyLibraryNotice.addEventListener("click", openSettings);

  async function refreshSettings() {
    await Promise.all([refreshCacheRoot(), refreshLibraryStatus(), refreshLibraryTracks(), refreshWarmStatus(), refreshPlaybackLog()]);
  }

  async function refreshCacheRoot() {
    const res = await fetch("/api/cache-root");
    const data = await res.json();
    infoPlaybackMode.textContent = data.playback_mode;
    infoCacheRoot.textContent = data.locked ? `${data.cache_root} (fixed by this deployment)` : data.cache_root;
  }

  async function refreshLibraryStatus() {
    const res = await fetch("/api/library-status");
    const data = await res.json();
    libraryStatus.textContent = data.exists
      ? `${data.track_count} track(s), last modified ${data.mtime}`
      : "not found";
  }

  async function refreshWarmStatus() {
    const res = await fetch("/api/cache-status");
    const data = await res.json();
    infoLastWarmRun.textContent = data.last_run || "Never (since last restart)";
    if (data.running) {
      warmStatus.textContent = `Running: ${data.current}/${data.total} — ${data.label}`;
      if (!warmPollTimer) {
        warmPollTimer = setInterval(refreshWarmStatus, 1500);
      }
    } else {
      warmStatus.textContent = "Idle";
      if (warmPollTimer) {
        clearInterval(warmPollTimer);
        warmPollTimer = null;
        refreshLibraryTracks();
        refreshPlaybackLog();
      }
    }
  }

  async function refreshPlaybackLog() {
    const res = await fetch("/api/logs/playback");
    const playbackLines = await res.json();
    playbackLog.textContent = playbackLines.length ? playbackLines.join("\n") : "(none)";
  }

  warmCacheBtn.addEventListener("click", async () => {
    await fetch("/warm-cache", { method: "POST" });
    refreshWarmStatus();
  });

  // -- library table (Add/Edit/Delete/Preview, sortable columns) --------

  let libraryTracks = [];
  let librarySort = { column: "artist", dir: "asc" };
  let selectedTrackIds = new Set();
  let editingTrackId = null;
  let pendingImportMode = null;

  const CACHE_STATUS_LABEL = { cached: "Cached", not_cached: "Not cached", failed: "Failed" };

  async function refreshLibraryTracks() {
    const res = await fetch("/api/library-tracks");
    libraryTracks = await res.json();
    const liveIds = new Set(libraryTracks.map((t) => t.id));
    for (const id of [...selectedTrackIds]) {
      if (!liveIds.has(id)) selectedTrackIds.delete(id);
    }
    renderLibraryTable();
  }

  function sortedTracks() {
    const { column, dir } = librarySort;
    const factor = dir === "asc" ? 1 : -1;
    return [...libraryTracks].sort((a, b) => {
      const av = String(a[column] ?? "").toLowerCase();
      const bv = String(b[column] ?? "").toLowerCase();
      if (av < bv) return -1 * factor;
      if (av > bv) return 1 * factor;
      return 0;
    });
  }

  function updateBulkDeleteButton() {
    const n = selectedTrackIds.size;
    bulkDeleteBtn.hidden = n === 0;
    bulkDeleteBtn.textContent = `Delete selected (${n})`;
  }

  function renderLibraryTable() {
    libraryTableBody.innerHTML = "";
    for (const track of sortedTracks()) {
      const tr = document.createElement("tr");

      const selectTd = document.createElement("td");
      selectTd.className = "col-select";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = selectedTrackIds.has(track.id);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) selectedTrackIds.add(track.id);
        else selectedTrackIds.delete(track.id);
        selectAllTracks.checked = libraryTracks.length > 0 && selectedTrackIds.size === libraryTracks.length;
        updateBulkDeleteButton();
      });
      selectTd.appendChild(checkbox);

      const artistTd = document.createElement("td");
      artistTd.className = "col-artist";
      artistTd.dataset.label = "Artist";
      artistTd.textContent = track.artist;
      const songTd = document.createElement("td");
      songTd.className = "col-song";
      songTd.dataset.label = "Song";
      songTd.textContent = track.song;
      const genreTd = document.createElement("td");
      genreTd.dataset.label = "Genre";
      genreTd.textContent = track.genre;
      const eraTd = document.createElement("td");
      eraTd.dataset.label = "Era";
      eraTd.textContent = track.era;

      const cacheTd = document.createElement("td");
      cacheTd.dataset.label = "Cache";
      const badge = document.createElement("span");
      badge.className = `cache-badge cache-badge-${track.cache_status}`;
      badge.textContent = CACHE_STATUS_LABEL[track.cache_status] || track.cache_status;
      if (track.cache_status === "failed") {
        badge.title = "Click for error details";
        badge.addEventListener("click", () => alert(track.cache_error || "Unknown error"));
      }
      cacheTd.appendChild(badge);

      const actionsTd = document.createElement("td");
      actionsTd.className = "library-actions";
      const previewBtn = document.createElement("button");
      previewBtn.type = "button";
      previewBtn.textContent = "Preview";
      previewBtn.addEventListener("click", () => window.open(track.url, "_blank"));
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.textContent = "Edit";
      editBtn.addEventListener("click", () => openTrackForm("edit", track));
      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "close-session-btn";
      deleteBtn.textContent = "Delete";
      deleteBtn.addEventListener("click", async () => {
        const label = track.artist ? `${track.artist} - ${track.song}` : track.url;
        if (!confirm(`Delete "${label}" from the library?`)) return;
        const result = await postJSON(`/api/library-tracks/${track.id}/delete`, {});
        if (result && result.error) {
          alert(result.error);
          return;
        }
        await refreshLibraryTracks();
      });
      actionsTd.append(previewBtn, editBtn, deleteBtn);

      tr.append(selectTd, artistTd, songTd, genreTd, eraTd, cacheTd, actionsTd);
      libraryTableBody.appendChild(tr);
    }

    selectAllTracks.checked = libraryTracks.length > 0 && selectedTrackIds.size === libraryTracks.length;
    updateBulkDeleteButton();
  }

  libraryTable.querySelectorAll("th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const column = th.dataset.sort;
      librarySort = librarySort.column === column
        ? { column, dir: librarySort.dir === "asc" ? "desc" : "asc" }
        : { column, dir: "asc" };
      librarySortField.value = librarySort.column;
      librarySortDir.value = librarySort.dir;
      renderLibraryTable();
    });
  });

  librarySortField.addEventListener("change", () => {
    librarySort = { column: librarySortField.value, dir: librarySortDir.value };
    renderLibraryTable();
  });

  librarySortDir.addEventListener("change", () => {
    librarySort = { column: librarySortField.value, dir: librarySortDir.value };
    renderLibraryTable();
  });

  selectAllTracks.addEventListener("change", () => {
    selectedTrackIds = selectAllTracks.checked ? new Set(libraryTracks.map((t) => t.id)) : new Set();
    renderLibraryTable();
  });

  bulkDeleteBtn.addEventListener("click", async () => {
    const n = selectedTrackIds.size;
    if (!confirm(`Delete ${n} selected song(s) from the library?`)) return;
    const result = await postJSON("/api/library-tracks/bulk-delete", { ids: [...selectedTrackIds] });
    if (result && result.error) {
      alert(result.error);
      return;
    }
    selectedTrackIds.clear();
    await refreshLibraryTracks();
  });

  // -- add/edit song form -------------------------------------------------

  function openTrackForm(mode, track) {
    editingTrackId = mode === "edit" ? track.id : null;
    trackFormTitle.textContent = mode === "edit" ? "Edit song" : "Add song";
    trackArtist.value = track ? track.artist : "";
    trackSong.value = track ? track.song : "";
    trackGenre.value = track ? track.genre : "";
    trackEra.value = track ? track.era : "";
    trackUrl.value = track ? track.url : "";
    trackSearchStatus.textContent = "";
    trackFormPanel.hidden = false;
    trackFormPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function closeTrackForm() {
    trackFormPanel.hidden = true;
    editingTrackId = null;
    trackForm.reset();
    trackSearchStatus.textContent = "";
  }

  addTrackBtn.addEventListener("click", () => openTrackForm("add", null));
  trackCancelBtn.addEventListener("click", closeTrackForm);

  trackPreviewBtn.addEventListener("click", () => {
    const url = trackUrl.value.trim();
    if (!url) {
      alert("Enter a URL first.");
      return;
    }
    window.open(url, "_blank");
  });

  trackSearchBtn.addEventListener("click", async () => {
    const artist = trackArtist.value.trim();
    const song = trackSong.value.trim();
    if (!artist || !song) {
      alert("Enter an artist and song first.");
      return;
    }
    trackSearchStatus.textContent = "Searching YouTube...";
    trackSearchBtn.disabled = true;
    const result = await postJSON("/api/library-tracks/search", { artist, song });
    trackSearchBtn.disabled = false;
    if (!result || result.error) {
      trackSearchStatus.textContent = (result && result.error) || "Search failed.";
      return;
    }
    trackUrl.value = result.url;
    const matchLabel = result.matched_by === "official_video" ? "official video match" : "most-viewed match";
    trackSearchStatus.textContent = `Found: "${result.title}" (${matchLabel}) — preview it before saving.`;
  });

  trackForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = {
      artist: trackArtist.value.trim(),
      song: trackSong.value.trim(),
      genre: trackGenre.value.trim(),
      era: trackEra.value.trim(),
      url: trackUrl.value.trim(),
    };
    const url = editingTrackId ? `/api/library-tracks/${editingTrackId}/update` : "/api/library-tracks";
    const result = await postJSON(url, body);
    if (!result || result.error) {
      alert((result && result.error) || "Save failed.");
      return;
    }
    closeTrackForm();
    await refreshLibraryTracks();
  });

  // -- CSV import (bulk add/replace) ---------------------------------------

  importAppendBtn.addEventListener("click", () => {
    pendingImportMode = "append";
    importCsvInput.click();
  });

  importReplaceBtn.addEventListener("click", () => {
    pendingImportMode = "replace";
    importCsvInput.click();
  });

  importCsvInput.addEventListener("change", async () => {
    const file = importCsvInput.files[0];
    const mode = pendingImportMode;
    importCsvInput.value = "";
    if (!file || !mode) return;

    const confirmText = mode === "replace"
      ? "Replace the entire library for everyone with this file? The current library is backed up server-side, but there's no undo from this UI."
      : `Add every row in "${file.name}" to the current library (existing songs are kept)?`;
    if (!confirm(confirmText)) return;

    const formData = new FormData();
    formData.append("csv", file);
    const res = await fetch(mode === "replace" ? "/upload" : "/upload-append", { method: "POST", body: formData });
    const text = await res.text();
    importResult.textContent = text;
    importResult.style.color = res.ok ? "" : "var(--danger)";
    if (res.ok) {
      refreshLibraryStatus();
      refreshLibraryTracks();
      fetchStatus();
    }
  });

  // -- startup: detect console vs. web mode ------------------------------
  //
  // /api/sessions 503s in console mode (no SessionManager running there,
  // see library_server.py's _require_session_manager) -- that's the cheap
  // way to tell which UI to show without a dedicated /api/config route.

  async function init() {
    const probe = await fetch("/api/sessions");
    if (probe.status === 503) {
      mode = "console";
      backToSessions.hidden = true;
      remote.hidden = false;
      pollTick();
      statusPollTimer = setInterval(pollTick, 2000);
      return;
    }

    mode = "web";
    const wanted = new URLSearchParams(location.search).get("session");
    if (wanted) {
      const res = await fetch(`/api/sessions/${encodeURIComponent(wanted)}/status`);
      if (res.ok) {
        selectSession(wanted);
        return;
      }
    }
    showSessionPicker();
  }

  init();
})();

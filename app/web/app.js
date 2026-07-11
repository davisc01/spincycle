(function () {
  const genreSelect = document.getElementById("genre-select");
  const eraSelect = document.getElementById("era-select");
  const statusMessage = document.getElementById("status-message");
  const skipBtn = document.getElementById("skip-btn");
  const stopBtn = document.getElementById("stop-btn");
  const launchPlayerBtn = document.getElementById("launch-player-btn");
  const backToSessions = document.getElementById("back-to-sessions");

  const sessionPicker = document.getElementById("session-picker");
  const sessionList = document.getElementById("session-list");
  const newSessionBtn = document.getElementById("new-session-btn");
  const remote = document.getElementById("remote");

  const settingsToggle = document.getElementById("settings-toggle");
  const settingsPanel = document.getElementById("settings");
  const libraryStatus = document.getElementById("library-status");
  const uploadForm = document.getElementById("upload-form");
  const uploadResult = document.getElementById("upload-result");
  const warmStatus = document.getElementById("warm-status");
  const warmCacheBtn = document.getElementById("warm-cache-btn");
  const cacheFailuresList = document.getElementById("cache-failures-list");
  const playbackLog = document.getElementById("playback-log");
  const cacheWarning = document.getElementById("cache-warning");

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

  function fillOptions(select, options, selected) {
    const placeholder = select === genreSelect ? "-- pick a genre --" : "-- pick an era --";
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

  const DIAL_DRAG_PX_PER_STEP = 24;
  const DIAL_SWEEP_DEG = 135; // indicator travels -135deg..+135deg

  function createDial(select, dialEl, readoutEl) {
    const knob = dialEl.querySelector(".dial-knob");
    const indicator = dialEl.querySelector(".dial-indicator");
    const prevBtn = dialEl.querySelector(".dial-step-prev");
    const nextBtn = dialEl.querySelector(".dial-step-next");

    function setIndex(newIndex) {
      const count = select.options.length;
      if (count === 0) return;
      const wrapped = ((newIndex % count) + count) % count;
      if (select.selectedIndex === wrapped) return;
      select.selectedIndex = wrapped;
      select.dispatchEvent(new Event("change"));
    }

    function step(delta) {
      setIndex(select.selectedIndex + delta);
    }

    prevBtn.addEventListener("click", () => step(-1));
    nextBtn.addEventListener("click", () => step(1));

    let wheelAccum = 0;
    knob.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        wheelAccum += event.deltaY;
        if (Math.abs(wheelAccum) >= 40) {
          step(wheelAccum > 0 ? 1 : -1);
          wheelAccum = 0;
        }
      },
      { passive: false }
    );

    let dragStartY = null;
    let dragStartIndex = 0;

    knob.addEventListener("pointerdown", (event) => {
      dragStartY = event.clientY;
      dragStartIndex = select.selectedIndex;
      knob.setPointerCapture(event.pointerId);
    });

    knob.addEventListener("pointermove", (event) => {
      if (dragStartY === null) return;
      const deltaY = dragStartY - event.clientY;
      const steps = Math.round(deltaY / DIAL_DRAG_PX_PER_STEP);
      if (steps !== 0) {
        setIndex(dragStartIndex + steps);
      }
    });

    function endDrag(event) {
      if (dragStartY === null) return;
      dragStartY = null;
      if (knob.hasPointerCapture(event.pointerId)) {
        knob.releasePointerCapture(event.pointerId);
      }
    }
    knob.addEventListener("pointerup", endDrag);
    knob.addEventListener("pointercancel", endDrag);

    function render() {
      const count = select.options.length;
      const index = select.selectedIndex;
      const fraction = count > 1 ? index / (count - 1) : 0;
      const angle = -DIAL_SWEEP_DEG + fraction * (2 * DIAL_SWEEP_DEG);
      indicator.style.setProperty("--angle", `${angle}deg`);
      const selectedOption = select.options[index];
      readoutEl.textContent = selectedOption ? selectedOption.textContent : "";
    }

    return { render };
  }

  const genreDial = createDial(genreSelect, document.getElementById("genre-dial"), document.getElementById("genre-readout"));
  const eraDial = createDial(eraSelect, document.getElementById("era-dial"), document.getElementById("era-readout"));

  function renderStatus(status) {
    fillOptions(genreSelect, status.genre_options, status.genre);
    fillOptions(eraSelect, status.era_options, status.era);
    genreDial.render();
    eraDial.render();
    statusMessage.textContent = status.status_message;
    statusMessage.classList.toggle("playing", status.playing);
    stopBtn.disabled = !status.playing;
    skipBtn.disabled = !status.playing;
    launchPlayerBtn.hidden = mode !== "web";

    if (status.cache_root_problem) {
      cacheWarning.textContent = `Cache folder isn't set up (${status.cache_root_problem}). See Deployment info in Settings for the configured path.`;
      cacheWarning.hidden = false;
    } else {
      cacheWarning.hidden = true;
    }
  }

  async function fetchStatus() {
    const res = await fetch(actionUrl("status"));
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
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return res.json();
  }

  genreSelect.addEventListener("change", async () => {
    const status = await postJSON(actionUrl("genre"), { genre: genreSelect.value || null });
    renderStatus(status);
  });

  eraSelect.addEventListener("change", async () => {
    const status = await postJSON(actionUrl("era"), { era: eraSelect.value || null });
    renderStatus(status);
  });

  skipBtn.addEventListener("click", async () => {
    const status = await postJSON(actionUrl("skip"));
    renderStatus(status);
  });

  stopBtn.addEventListener("click", async () => {
    const status = await postJSON(actionUrl("stop"));
    renderStatus(status);
  });

  launchPlayerBtn.addEventListener("click", () => {
    window.open(`/player?session=${encodeURIComponent(session)}`, "_blank");
  });

  backToSessions.addEventListener("click", (event) => {
    event.preventDefault();
    showSessionPicker();
  });

  // -- session picker (web mode only) ------------------------------------

  function renderSessionList(sessions) {
    sessionList.innerHTML = "";
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
    sessionPicker.hidden = true;
    remote.hidden = false;
    backToSessions.hidden = false;
    history.pushState(null, "", `/?session=${encodeURIComponent(name)}`);
    fetchStatus();
    if (statusPollTimer) clearInterval(statusPollTimer);
    statusPollTimer = setInterval(fetchStatus, 2000);
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

  async function refreshSettings() {
    await Promise.all([refreshCacheRoot(), refreshLibraryStatus(), refreshWarmStatus(), refreshCacheFailures(), refreshPlaybackLog()]);
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
      ? `${data.size} bytes, last modified ${data.mtime}`
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
        refreshCacheFailures();
        refreshPlaybackLog();
      }
    }
  }

  async function refreshPlaybackLog() {
    const res = await fetch("/api/logs/playback");
    const playbackLines = await res.json();
    playbackLog.textContent = playbackLines.length ? playbackLines.join("\n") : "(none)";
  }

  async function refreshCacheFailures() {
    const res = await fetch("/api/cache-failures");
    const failures = await res.json();
    renderCacheFailures(failures);
  }

  function renderCacheFailures(failures) {
    cacheFailuresList.innerHTML = "";
    if (!failures.length) {
      const li = document.createElement("li");
      li.textContent = "(none)";
      cacheFailuresList.appendChild(li);
      return;
    }

    for (const failure of failures) {
      const li = document.createElement("li");
      li.className = "failure-item";

      const info = document.createElement("div");
      info.className = "failure-info";
      const title = document.createElement("span");
      title.className = "failure-title";
      title.textContent = failure.artist ? `${failure.artist} - ${failure.song}` : failure.url;
      const meta = document.createElement("span");
      meta.className = "failure-meta";
      meta.textContent = `${failure.genre} / ${failure.era} — ${failure.error}`;
      info.append(title, meta);

      const urlInput = document.createElement("input");
      urlInput.type = "text";
      urlInput.className = "failure-url-input";
      urlInput.value = failure.url;

      const actions = document.createElement("div");
      actions.className = "failure-actions";
      const saveBtn = document.createElement("button");
      saveBtn.type = "button";
      saveBtn.textContent = "Save";
      saveBtn.addEventListener("click", async () => {
        const result = await postJSON("/api/cache-failures/edit", { url: failure.url, new_url: urlInput.value.trim() });
        if (result.error) {
          alert(result.error);
          return;
        }
        renderCacheFailures(result);
      });
      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "close-session-btn";
      removeBtn.textContent = "Remove";
      removeBtn.addEventListener("click", async () => {
        const result = await postJSON("/api/cache-failures/remove", { url: failure.url });
        if (result.error) {
          alert(result.error);
          return;
        }
        renderCacheFailures(result);
      });
      actions.append(saveBtn, removeBtn);

      li.append(info, urlInput, actions);
      cacheFailuresList.appendChild(li);
    }
  }

  uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(uploadForm);
    const res = await fetch("/upload", { method: "POST", body: formData });
    const text = await res.text();
    uploadResult.textContent = text;
    uploadResult.style.color = res.ok ? "" : "var(--danger)";
    if (res.ok) {
      uploadForm.reset();
      refreshLibraryStatus();
      fetchStatus();
    }
  });

  warmCacheBtn.addEventListener("click", async () => {
    // Optimistically clear right away -- the server clears its persisted
    // failures list as soon as the run starts too (see _run_warm_cache),
    // but that happens in a background thread, so don't wait on a fetch
    // round-trip to race it. The poll loop below will repopulate with
    // this run's real failures once it finishes.
    renderCacheFailures([]);
    await fetch("/warm-cache", { method: "POST" });
    refreshWarmStatus();
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
      fetchStatus();
      statusPollTimer = setInterval(fetchStatus, 2000);
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

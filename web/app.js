(function () {
  const genreSelect = document.getElementById("genre-select");
  const eraSelect = document.getElementById("era-select");
  const statusMessage = document.getElementById("status-message");
  const skipBtn = document.getElementById("skip-btn");
  const stopBtn = document.getElementById("stop-btn");

  const settingsToggle = document.getElementById("settings-toggle");
  const settingsPanel = document.getElementById("settings");
  const libraryStatus = document.getElementById("library-status");
  const uploadForm = document.getElementById("upload-form");
  const uploadResult = document.getElementById("upload-result");
  const warmStatus = document.getElementById("warm-status");
  const warmCacheBtn = document.getElementById("warm-cache-btn");
  const cacheLog = document.getElementById("cache-log");
  const playbackLog = document.getElementById("playback-log");
  const cacheRootForm = document.getElementById("cache-root-form");
  const cacheRootInput = document.getElementById("cache-root-input");
  const cacheRootResult = document.getElementById("cache-root-result");
  const cacheWarning = document.getElementById("cache-warning");

  let warmPollTimer = null;

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

  function renderStatus(status) {
    fillOptions(genreSelect, status.genre_options, status.genre);
    fillOptions(eraSelect, status.era_options, status.era);
    statusMessage.textContent = status.status_message;
    statusMessage.classList.toggle("playing", status.playing);
    stopBtn.disabled = !status.playing;
    skipBtn.disabled = !status.playing;

    if (status.cache_root_problem) {
      cacheWarning.textContent = `Cache folder isn't set up (${status.cache_root_problem}). Tap here to fix it in Settings.`;
      cacheWarning.hidden = false;
    } else {
      cacheWarning.hidden = true;
    }
  }

  async function fetchStatus() {
    const res = await fetch("/api/status");
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
    const status = await postJSON("/api/genre", { genre: genreSelect.value || null });
    renderStatus(status);
  });

  eraSelect.addEventListener("change", async () => {
    const status = await postJSON("/api/era", { era: eraSelect.value || null });
    renderStatus(status);
  });

  skipBtn.addEventListener("click", async () => {
    const status = await postJSON("/api/skip");
    renderStatus(status);
  });

  stopBtn.addEventListener("click", async () => {
    const status = await postJSON("/api/stop");
    renderStatus(status);
  });

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
    await Promise.all([refreshCacheRoot(), refreshLibraryStatus(), refreshWarmStatus(), refreshLogs()]);
  }

  async function refreshCacheRoot() {
    const res = await fetch("/api/cache-root");
    const data = await res.json();
    cacheRootInput.value = data.cache_root;
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
        refreshLogs();
      }
    }
  }

  async function refreshLogs() {
    const [cacheRes, playbackRes] = await Promise.all([
      fetch("/api/logs/cache"),
      fetch("/api/logs/playback"),
    ]);
    const cacheLines = await cacheRes.json();
    const playbackLines = await playbackRes.json();
    cacheLog.textContent = cacheLines.length ? cacheLines.join("\n") : "(none)";
    playbackLog.textContent = playbackLines.length ? playbackLines.join("\n") : "(none)";
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
    await fetch("/warm-cache", { method: "POST" });
    refreshWarmStatus();
  });

  cacheRootForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = await postJSON("/api/cache-root", { cache_root: cacheRootInput.value });
    if (data.error) {
      cacheRootResult.textContent = data.error;
      cacheRootResult.style.color = "var(--danger)";
    } else {
      cacheRootInput.value = data.cache_root;
      cacheRootResult.textContent = `Cache folder set to ${data.cache_root}`;
      cacheRootResult.style.color = "";
      fetchStatus();
    }
  });

  // -- polling ---------------------------------------------------------

  fetchStatus();
  setInterval(fetchStatus, 2000);
})();

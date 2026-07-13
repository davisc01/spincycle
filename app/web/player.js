(function () {
  const params = new URLSearchParams(location.search);
  const session = params.get("session");
  const video = document.getElementById("v");
  const overlay = document.getElementById("overlay");
  const tapToPlay = document.getElementById("tap-to-play");
  const trackOverlay = document.getElementById("track-overlay");

  if (!session) {
    overlay.textContent = "No session specified -- open this page from the web remote's \"Launch Player\" button.";
    return;
  }

  let currentUrl = null;
  let overlayHideTimer = null;

  function showTrackOverlay(track) {
    if (!track) return;
    const lines = [track.artist, track.song, `${track.genre} / ${track.era}`].filter(Boolean);
    if (lines.length === 0) return;
    trackOverlay.textContent = lines.join("\n");
    trackOverlay.classList.add("shown");
    if (overlayHideTimer) clearTimeout(overlayHideTimer);
    overlayHideTimer = setTimeout(() => {
      trackOverlay.classList.remove("shown");
      overlayHideTimer = null;
    }, 5000);
  }

  function hideTrackOverlay() {
    if (overlayHideTimer) {
      clearTimeout(overlayHideTimer);
      overlayHideTimer = null;
    }
    trackOverlay.classList.remove("shown");
  }

  function showTapToPlay() {
    tapToPlay.classList.add("shown");
  }

  function hideTapToPlay() {
    tapToPlay.classList.remove("shown");
  }

  tapToPlay.addEventListener("click", () => {
    video.play().then(hideTapToPlay).catch(() => {});
  });

  video.addEventListener("playing", hideTapToPlay);

  async function poll() {
    let status;
    try {
      const res = await fetch(`/api/sessions/${encodeURIComponent(session)}/status`);
      if (!res.ok) {
        overlay.textContent = res.status === 404 ? "Session closed." : `Error: ${res.status}`;
        overlay.style.display = "";
        return;
      }
      status = await res.json();
    } catch (e) {
      return; // transient network hiccup -- just try again next poll
    }

    // "Now playing: X" is redundant with the track-overlay above, which
    // already shows artist/song for the first 5s of each video -- suppress
    // it here so this bar is only visible for loading/cache-miss/error/idle
    // messages, not just repeating what the overlay already said.
    const message = status.status_message || "";
    const showMessage = message && !message.startsWith("Now playing:");
    overlay.textContent = showMessage ? message : "";
    overlay.style.display = showMessage ? "" : "none";

    if (status.video_url !== currentUrl) {
      currentUrl = status.video_url;
      if (currentUrl) {
        video.src = currentUrl;
        video.play().catch(() => {
          // Autoplay-with-sound blocked (common on Safari) until the
          // viewer interacts with this tab once -- show an explicit
          // button rather than relying on the browser's own paused icon,
          // which is easy to miss (see player.html).
          showTapToPlay();
        });
        showTrackOverlay(status.current_track);
      } else {
        video.removeAttribute("src");
        video.load();
        hideTapToPlay();
        hideTrackOverlay();
      }
    }
  }

  video.addEventListener("ended", () => {
    fetch(`/api/sessions/${encodeURIComponent(session)}/video-ended`, { method: "POST" });
  });

  poll();
  setInterval(poll, 2000);
})();

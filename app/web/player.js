(function () {
  const params = new URLSearchParams(location.search);
  const session = params.get("session");
  const video = document.getElementById("v");
  const overlay = document.getElementById("overlay");

  if (!session) {
    overlay.textContent = "No session specified -- open this page from the web remote's \"Launch Player\" button.";
    return;
  }

  let currentUrl = null;

  async function poll() {
    let status;
    try {
      const res = await fetch(`/api/sessions/${encodeURIComponent(session)}/status`);
      if (!res.ok) {
        overlay.textContent = res.status === 404 ? "Session closed." : `Error: ${res.status}`;
        return;
      }
      status = await res.json();
    } catch (e) {
      return; // transient network hiccup -- just try again next poll
    }

    overlay.textContent = status.status_message || "";

    if (status.video_url !== currentUrl) {
      currentUrl = status.video_url;
      if (currentUrl) {
        video.src = currentUrl;
        video.play().catch(() => {
          // Autoplay-with-sound may be blocked until the viewer interacts
          // with this tab once -- not fixable from here, see player.html.
        });
      } else {
        video.removeAttribute("src");
        video.load();
      }
    }
  }

  video.addEventListener("ended", () => {
    fetch(`/api/sessions/${encodeURIComponent(session)}/video-ended`, { method: "POST" });
  });

  poll();
  setInterval(poll, 2000);
})();

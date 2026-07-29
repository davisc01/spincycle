(function () {
  const params = new URLSearchParams(location.search);
  const session = params.get("session"); // null in console mode

  const heading = document.getElementById("dj-heading");
  const statusLine = document.getElementById("dj-status");
  const songList = document.getElementById("song-list");

  function tracksUrl() {
    return session ? `/api/sessions/${encodeURIComponent(session)}/tracks` : "/api/tracks";
  }

  function queueUrl() {
    return session ? `/api/sessions/${encodeURIComponent(session)}/queue-next` : "/api/queue-next";
  }

  function trackLabel(track) {
    return track.artist ? `${track.artist} - ${track.song}` : track.url;
  }

  function render(data) {
    heading.textContent = data.genre && data.era ? `${data.genre} / ${data.era}` : "DJ";

    if (!data.tracks.length) {
      statusLine.textContent = data.genre && data.era
        ? "No tracks in this genre/era."
        : "Pick a genre and era on the remote tab first.";
      songList.innerHTML = "";
      return;
    }
    statusLine.textContent = "";

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
        try {
          const res = await fetch(queueUrl(), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: track.url }),
          });
          const result = await res.json();
          if (!res.ok) {
            alert(result.error || "Couldn't queue that track.");
            queueBtn.disabled = false;
            return;
          }
          render({ ...data, current_track: result.current_track, queued_track: result.queued_track });
        } catch (e) {
          alert("Couldn't reach the server.");
          queueBtn.disabled = false;
        }
      });
      actions.appendChild(queueBtn);

      li.append(info, actions);
      songList.appendChild(li);
    }
  }

  async function poll() {
    let res;
    try {
      res = await fetch(tracksUrl());
    } catch (e) {
      return; // transient network hiccup -- just try again next poll
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      heading.textContent = "DJ";
      statusLine.textContent = body.error || `Error: ${res.status}`;
      songList.innerHTML = "";
      return;
    }
    const data = await res.json();
    render(data);
  }

  poll();
  setInterval(poll, 2000);
})();

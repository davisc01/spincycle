# Container (web) deployment target

Unlike `deploy/raspberrypi/` (a self-contained install script for one
physical device), this target is just "run the same `app/` image
somewhere with `SPINCYCLE_PLAYBACK_MODE=web`" -- no mpv, no DRM/ALSA, no
privileged access to host devices needed. A browser tab you open via
"Launch Player" becomes the player instead (see `player.py`'s
`BrowserPlayer` and `sessions.py`). That makes it a good fit for a NAS,
a home server, a Docker/Podman host, or any Kubernetes distribution --
pick whichever fits your own infrastructure. This directory intentionally
doesn't prescribe one.

This repo only builds and publishes the image -- via
[`.github/workflows/build-container-image.yml`](../../.github/workflows/build-container-image.yml),
which builds `app/Dockerfile` and pushes `ghcr.io/davisc01/spincycle:latest`
to GHCR on every push to `app/**`. Actual deployment (a Compose file, raw
`podman run`/`docker run`, Kubernetes manifests, a systemd unit, whatever
your environment already uses) is up to you -- this README covers what
the image expects so you can wire it into any of those.

See the main [README.md](../../README.md) for the overall project
description, and its "Using the web remote" section for how the
web-mode session picker works.

## What the image needs

- **`SPINCYCLE_PLAYBACK_MODE=web`** -- swaps the mpv-on-console `Player`
  for the browser-based `BrowserPlayer` and relaxes `config.FORMAT_SELECTOR`
  to a looser, higher-resolution selector (decoding happens client-side in
  the viewer's browser, not on this host -- see `config.py`).
- **`SPINCYCLE_CACHE_ROOT=/cache`** (or any path you choose) -- pin the
  video cache location and bind-mount/PV that path so downloaded videos
  survive a container restart. Without a persistent volume here, every
  restart re-downloads the entire library.
- **A persistent volume for `/app/config`** -- `library.db` (your video
  library, a local SQLite file) and `settings.json` (runtime settings, e.g.
  cache root) live here. Mount this from a volume too, or edits made via
  the web remote's Library panel (add/edit/delete tracks, CSV import,
  warm-cache) won't survive a restart.
- **Port 80** (`config.LIBRARY_SERVER_PORT`) -- the web remote and JSON
  API. No authentication -- see "Security" below before exposing this
  anywhere beyond a trusted LAN.

## Running it directly (Docker/Podman)

```bash
docker run -d --name spincycle \
  -p 80:80 \
  -v spincycle-config:/app/config \
  -v spincycle-cache:/cache \
  -e SPINCYCLE_PLAYBACK_MODE=web \
  -e SPINCYCLE_CACHE_ROOT=/cache \
  ghcr.io/davisc01/spincycle:latest
```

(substitute `podman` for `docker` if that's your runtime -- no
`--privileged`/`--network host`/device bind-mounts needed here, unlike
`deploy/raspberrypi/install.sh`; this target doesn't touch DRM/ALSA/the
physical console at all).

## Running it on Kubernetes

Roughly, you want:

- A `Deployment` running `ghcr.io/davisc01/spincycle:latest` with
  `SPINCYCLE_PLAYBACK_MODE=web` and `SPINCYCLE_CACHE_ROOT=/cache` set,
  **`replicas: 1`** (see "Single replica only" below -- this is a hard
  requirement, not a default to bump), exposing container port 80.
- Two `PersistentVolumeClaim`s mounted into the pod: one at `/cache`
  (video cache -- gets large, size it for your library), one at
  `/app/config` (small -- just `library.db`/`settings.json`).
  Any `StorageClass` your cluster provides works; there's nothing
  Spin-Cycle-specific about the storage.
- A `Service` (ClusterIP is enough if you're fronting it with your own
  Ingress/LoadBalancer setup) exposing port 80.
- However you deploy manifests already -- `kubectl apply`, Argo CD, Flux,
  Helm, plain YAML in another repo -- works the same way here; nothing
  about the image assumes a particular GitOps tool or cluster.

After a push here builds a new image, roll it out with whatever your
deploy tooling uses, e.g.:

```
kubectl rollout restart deployment/spincycle
```

## Single replica only

Sessions (`sessions.py`'s `SessionManager`) live in the running pod's
memory, not shared storage -- a second replica would split traffic across
two independent, inconsistent session sets, with no coordination between
them. Keep this at one replica. If you need more capacity, look at scaling
vertically or running independent single-replica deployments per audience
rather than scaling this one out horizontally.

## Security

`library_server.py` has no authentication -- it's designed for LAN-only
trust (same level as SSH access to a box), not as an internet-facing
service. If you expose this beyond your own network (a public Ingress,
port-forwarding through a home router, etc.), put it behind your own
auth layer (a reverse proxy with basic auth, a VPN, an OAuth-aware
ingress, etc.) -- Spin Cycle itself won't stop anyone who can reach the
port from uploading a new library or controlling playback.

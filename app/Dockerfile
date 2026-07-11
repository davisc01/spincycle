# trixie (not bookworm) to match Raspberry Pi OS's own Debian generation --
# libasound2's vc4-hdmi.conf (bind-mounted from the host in
# deploy/raspberrypi/install.sh) needs a matching-era alsa-lib runtime to
# actually negotiate audio correctly. See CLAUDE.md's "Known gaps" for the
# debugging history.
FROM python:3.11-slim-trixie

RUN apt-get update && apt-get install -y --no-install-recommends \
    mpv \
    ffmpeg \
    ca-certificates \
    alsa-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENTRYPOINT ["python3", "main.py"]

# pokeldn as a web app: the desktop GUI served to a browser, reaching the radio through the network
# bridge (firmware/bridge). docs/docker.md.

# PKHeX, the Pokemon builder the app starts as a helper process (pokeldn/pokemon.py).
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS pkhex
ARG TARGETARCH
WORKDIR /src
COPY services/pkhex/ ./
RUN case "$TARGETARCH" in arm64) rid=linux-arm64 ;; *) rid=linux-x64 ;; esac \
 && dotnet publish -c Release -r "$rid" -o /out

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/data/home \
    POKELDN_DATA=/data \
    POKELDN_PKHEX=/opt/pkhex/pokeldn-pkhex \
    POKELDN_GUI_WEB=8550 \
    FLET_SERVER_IP=0.0.0.0
WORKDIR /app

# The LDN package installs editable from vendor/, so it comes before the requirements.
COPY vendor/ vendor/
COPY requirements.txt ./
COPY gui/requirements.txt gui/
# Beside the original, so its `-r ../requirements.txt` still resolves; no pyinstaller in a source run.
RUN grep -v '^pyinstaller' gui/requirements.txt > gui/requirements.docker.txt \
 && pip install -r gui/requirements.docker.txt

COPY --from=pkhex /out/pokeldn-pkhex /opt/pkhex/pokeldn-pkhex
COPY . .

VOLUME /data
EXPOSE 8550
CMD ["python", "gui/main.py"]

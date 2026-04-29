FROM python:3.11-slim

# Wine installation for running AssettoCorsaEVOServer.exe on Linux
# Approach inspired by VandaLpr/acevo-docker-server (https://github.com/VandaLpr/acevo-docker-server)
RUN dpkg --add-architecture i386 \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      wget gnupg ca-certificates xvfb xauth \
 && mkdir -pm755 /etc/apt/keyrings \
 && wget -qO /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key \
 && echo "deb [arch=amd64,i386 signed-by=/etc/apt/keyrings/winehq-archive.key] https://dl.winehq.org/wine-builds/debian/ bookworm main" \
    > /etc/apt/sources.list.d/winehq.list \
 && apt-get update \
 && apt-get install -y winehq-stable \
 && rm -rf /var/lib/apt/lists/*

# Pre-initialize Wine prefix at build time (WoW64 mode — handles both 32 and 64-bit exes)
RUN WINEPREFIX=/root/.wine WINEDEBUG=-all \
    xvfb-run wine wineboot --init && \
    WINEPREFIX=/root/.wine wineserver -w

WORKDIR /panel

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /panel/data /aceserver/configs

ENV DEPLOY_MODE=docker \
    ACESERVER_DIR=/aceserver \
    CONFIGS_DIR=/aceserver/configs \
    DATABASE_URL=sqlite:////panel/data/ace_evo.db \
    SESSION_COOKIE_SECURE=false \
    WINEPREFIX=/root/.wine \
    WINEDEBUG=-all \
    DISPLAY=:99

EXPOSE 4300

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

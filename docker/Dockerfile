FROM ich777/winehq-baseimage

# Python 3 + virtual display (Wine already provided and configured by base image)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-venv xvfb xauth \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /panel

COPY requirements.txt .
RUN python3 -m venv /panel/venv \
 && /panel/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /panel/data /aceserver/configs

ENV DEPLOY_MODE=docker \
    ACESERVER_DIR=/aceserver \
    CONFIGS_DIR=/aceserver/configs \
    DATABASE_URL=sqlite:////panel/data/ace_evo.db \
    SESSION_COOKIE_SECURE=false \
    WINEPREFIX=/root/.wine \
    WINEDEBUG=-all \
    WINEDLLOVERRIDES="winemenubuilder.exe=d;setupapi=b;mscoree=d;mshtml=d" \
    WINEARCH=win64 \
    DISPLAY=:99 \
    PATH=/panel/venv/bin:$PATH

EXPOSE 4300

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

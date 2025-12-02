# syntax=docker/dockerfile:1.7
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install Brave Browser and runtime dependencies.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        gnupg \
        apt-transport-https \
    && curl -fsSLo /usr/share/keyrings/brave-browser-archive-keyring.gpg https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg arch=amd64] https://brave-browser-apt-release.s3.brave.com/ stable main" > /etc/apt/sources.list.d/brave-browser-release.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        brave-browser \
        xvfb \
        xdg-utils \
        tini \
        fonts-liberation \
        libasound2 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libatspi2.0-0 \
        libdrm2 \
        libgbm1 \
        libgtk-3-0 \
        libnss3 \
        libx11-xcb1 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libxkbcommon0 \
        libxshmfence1 \
    && apt-get purge -y curl gnupg apt-transport-https \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv "$VIRTUAL_ENV" \
    && "$VIRTUAL_ENV/bin/pip" install --upgrade pip

RUN useradd --create-home --home-dir /app --shell /bin/bash alita
WORKDIR /app

COPY requirements.txt ./
RUN "$VIRTUAL_ENV/bin/pip" install --no-cache-dir -r requirements.txt

COPY --chown=alita:alita src ./src
COPY --chown=alita:alita README.md ./README.md
COPY docker/entrypoint.sh /usr/local/bin/alita-entrypoint.sh
RUN chmod +x /usr/local/bin/alita-entrypoint.sh

ENV ALITA_DISABLE_SANDBOX=true \
    ALITA_BROWSER_HEADLESS=false \
    ALITA_XVFB_DISPLAY=:99 \
    ALITA_XVFB_SCREEN=1600x900x24 \
    XDG_RUNTIME_DIR=/tmp/alita-runtime

RUN mkdir -p "$XDG_RUNTIME_DIR" \
    && chown alita:alita "$XDG_RUNTIME_DIR" \
    && chmod 700 "$XDG_RUNTIME_DIR" \
    && install -d -m 1777 /tmp/.X11-unix

USER alita
EXPOSE 4000

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/alita-entrypoint.sh"]
CMD []

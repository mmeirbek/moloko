# Headless Chromium for the agents' browser tool and PDF export (sandbox runner, spec 16).
# Run by the sandbox runner only: non-root (uid 10001), read-only root, no capabilities,
# network = the internal browser network (egress proxy only) or none for PDF printing.
# Debian ships the command-line build as chromium-headless-shell; if a mirror lacks it,
# the full chromium package is used through a small wrapper with the same name.
FROM debian:trixie-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-dejavu-core fonts-noto-core fonts-noto-color-emoji ca-certificates \
    && (apt-get install -y --no-install-recommends chromium-headless-shell \
        || (apt-get install -y --no-install-recommends chromium \
            && printf '#!/bin/sh\nexec chromium --headless "$@"\n' > /usr/local/bin/chromium-headless-shell \
            && chmod 755 /usr/local/bin/chromium-headless-shell)) \
    && command -v chromium-headless-shell \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
USER app
WORKDIR /workspace

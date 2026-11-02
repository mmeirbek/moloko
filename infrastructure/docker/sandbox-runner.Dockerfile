# Image of the agents' commands (SANDBOX_IMAGE, default moloko-sandbox:local): every
# `terminal_run` starts a fresh container from it. The sandbox runner (app/sandbox/runner.py)
# fixes everything else: uid 10001, read-only root, no capabilities, no-new-privileges,
# limits, only the task's folder mounted, and no network — or, when the agent asks for
# package downloads, only the package-registry proxy (service `egress-packages`).
#
# Python 3.12 + Node.js 22 LTS (node, npm, npx) + git + make + headless Chromium for browser
# tests (Playwright). Node is copied from the official image pinned below (the same release as
# the frontend's node:22.23.4-alpine, but built for glibc like this Debian base); git, make,
# Chromium and the fonts are Debian trixie packages (security updates come with a rebuild, as
# in the browser image). Chromium brings the system libraries a browser needs, so Playwright's
# own browser build (`npx playwright install chromium`, downloaded with network "packages"
# into the workspace) runs here too; or tests use this one: CHROMIUM_PATH.
#
# Built by infrastructure/scripts/deploy.sh and e2e.sh:
#   docker compose --profile sandbox-image build sandbox-image
FROM node:22.23.4-trixie-slim AS node

FROM python:3.12.16-slim
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && apt-get update \
    && apt-get install -y --no-install-recommends git make ca-certificates \
        fonts-dejavu-core fonts-noto-core fonts-noto-color-emoji \
    && (apt-get install -y --no-install-recommends chromium-headless-shell \
        || (apt-get install -y --no-install-recommends chromium \
            && printf '#!/bin/sh\nexec chromium --headless "$@"\n' > /usr/local/bin/chromium-headless-shell \
            && chmod 755 /usr/local/bin/chromium-headless-shell)) \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && node --version && npm --version && git --version && command -v chromium-headless-shell
USER app
WORKDIR /workspace

# syntax=docker/dockerfile:1
# The `codex` service (apps/api/app/codex_service/server.py): OpenAI's official Codex CLI,
# signed in with the owner's ChatGPT account, running agents' coding tasks in their workspace.
# Build context: repository root. linux/amd64 and linux/arm64.
#
# The same tools as the agents' command image (sandbox-runner.Dockerfile: Python 3.12,
# Node.js 22, git, make) so the commands Codex runs find them — without the browser. Codex
# is the release binary of openai/codex (Apache-2.0), pinned with its SHA-256; nothing is
# installed at run time. The sign-in (auth.json) lives in the codex-home volume, never here.
FROM node:22.23.4-trixie-slim AS node

FROM python:3.12.16-slim AS codex
ARG TARGETARCH
ARG CODEX_VERSION=0.166.0
ARG CODEX_SHA256_AMD64=a0bf572d2f93f056c6712a6da348e96078dc84f3885fd7be67807ef389cb3978
ARG CODEX_SHA256_ARM64=94eb707605ec2646b2e05b7edf7c4e7b3ccf02b16237c34ae9beb8cfb7f810a9
RUN set -eu; \
    case "${TARGETARCH:-amd64}" in \
      amd64) triple=x86_64-unknown-linux-musl; sum="$CODEX_SHA256_AMD64" ;; \
      arm64) triple=aarch64-unknown-linux-musl; sum="$CODEX_SHA256_ARM64" ;; \
      *) echo "unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    url="https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-${triple}.tar.gz"; \
    python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], '/tmp/codex.tar.gz')" "$url"; \
    echo "$sum  /tmp/codex.tar.gz" | sha256sum -c -; \
    mkdir /tmp/codex && tar -xzf /tmp/codex.tar.gz -C /tmp/codex; \
    install -m 0755 /tmp/codex/codex-${triple} /usr/local/bin/codex; \
    /usr/local/bin/codex --version

FROM python:3.12.16-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CODEX_HOME=/codex-home \
    HOME=/codex-home
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
COPY --from=codex /usr/local/bin/codex /usr/local/bin/codex
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && apt-get update \
    && apt-get install -y --no-install-recommends git make ca-certificates ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /codex-home --shell /usr/sbin/nologin app \
    && mkdir -p /codex-home /opt/moloko && chown app:app /codex-home \
    && codex --version && node --version && git --version
COPY --chown=root:root apps/api/app/codex_service/server.py /opt/moloko/codex_server.py
USER app
WORKDIR /data/workspaces
EXPOSE 8095
CMD ["python", "/opt/moloko/codex_server.py"]

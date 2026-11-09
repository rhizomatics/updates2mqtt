# Pinned tool versions, kept here in one place and updated by Dependabot. These stages are only
# copied from, never built. Docker tools come from their release images rather than apt, which lags
# upstream releases.
FROM docker:29.9.3-cli AS docker-cli
FROM docker/buildx-bin:0.38.2 AS docker-buildx
FROM docker/compose-bin:v5.7.0 AS docker-compose
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv


FROM python:3.14-slim AS builder

# Build stage: uv and the build backend stay here, only the finished venv is copied to the runtime image
COPY --from=uv /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1
ENV UV_NO_DEV=1
ENV UV_LINK_MODE=copy
ENV UV_PYTHON_DOWNLOADS=0

WORKDIR /app

ADD uv.lock /app/uv.lock
ADD pyproject.toml /app/pyproject.toml
RUN uv sync --locked --no-install-project --no-editable

ADD src /app/src
ADD README.md /app/README.md
RUN uv sync --locked --no-editable


FROM python:3.14-slim

RUN apt-get -y update && apt-get -y upgrade && \
  apt-get -y install git ca-certificates mosquitto-clients jq && \
  rm -rf /var/lib/apt/lists/*

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker-buildx /buildx /usr/libexec/docker/cli-plugins/docker-buildx
COPY --from=docker-compose /docker-compose /usr/libexec/docker/cli-plugins/docker-compose
RUN docker --version && docker buildx version && docker compose version

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
ADD scripts/healthcheck.sh /app
RUN chmod ug+x /app/healthcheck.sh
ADD common_packages.yaml /app
RUN mkdir /app/.cache && chmod a+rw /app/.cache

ENV PATH="/app/.venv/bin:$PATH"
# Use explicit path and python executable rather than `uv run` to get proper signal handling
ENTRYPOINT ["python", "-m", "updates2mqtt"]

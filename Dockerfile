FROM python:3.14-slim AS builder

# Build stage: uv and the build backend stay here, only the finished venv is copied to the runtime image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

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

RUN apt-get -y update && apt-get -y upgrade
RUN apt-get -y install git ca-certificates
RUN install -m 0755 -d /etc/apt/keyrings
ADD https://download.docker.com/linux/debian/gpg /etc/apt/keyrings/docker.asc
RUN chmod a+r /etc/apt/keyrings/docker.asc

# Add the docker repository to apt sources:
RUN echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
   tee /etc/apt/sources.list.d/docker.list > /dev/null

RUN apt-get -y update && \
  apt-get -y install docker-ce-cli docker-buildx-plugin docker-compose-plugin mosquitto-clients jq && \
  rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
ADD scripts/healthcheck.sh /app
RUN chmod ug+x /app/healthcheck.sh
ADD common_packages.yaml /app
RUN mkdir /app/.cache && chmod a+rw /app/.cache

ENV PATH="/app/.venv/bin:$PATH"
# Use explicit path and python executable rather than `uv run` to get proper signal handling
ENTRYPOINT ["python", "-m", "updates2mqtt"]

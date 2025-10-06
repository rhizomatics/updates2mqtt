FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1

RUN apt-get -y update && apt-get -y upgrade
RUN apt-get -y install git ca-certificates curl
RUN install -m 0755 -d /etc/apt/keyrings
RUN curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
RUN chmod a+r /etc/apt/keyrings/docker.asc

# Add the docker repository to apt sources:
RUN echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
   tee /etc/apt/sources.list.d/docker.list > /dev/null

RUN apt-get -y update
RUN apt-get -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin mosquitto-clients jq

WORKDIR /app

ADD uv.lock /app/uv.lock
ADD pyproject.toml /app/pyproject.toml
RUN uv sync --locked --no-install-project

ADD src /app
ADD scripts/healthcheck.sh /app
RUN chmod ug+x /app/healthcheck.sh
ADD README.md /app/README.md
ADD common_packages.yaml /app


RUN uv sync --locked

ENV PATH="/app/.venv/bin:$PATH"
# Use explicit path and python executable rather than `uv run` to get proper signal handling
ENTRYPOINT ["python", "-m", "updates2mqtt"]

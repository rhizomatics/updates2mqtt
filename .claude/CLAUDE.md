# CLAUDE.md

Guidance for coding agents working in this repository. `AGENTS.md` is a link to this file.

## Project Context

Updates2MQTT is a Python service, published to PyPI and as a Docker image on GHCR, that checks
Docker images, Portainer stacks and local Git-based builds for updates and publishes them over MQTT
as Home Assistant MQTT Update entities, optionally applying the update when asked.

The project uses Ruff for formatting and linting, uv for dependency management, mypy and ty for type
checking, pytest for testing, codespell for spell checking and deptry for dependency checks.

Documentation uses properdocs with the MaterialX theme and is published to GitHub Pages at
updates2mqtt.rhizomatics.org.uk. `README.md` and the pages in `docs/` are the English sources;
`README.<lang>.md` and `docs/<lang>/` are translations, so keep them in step when changing
user-facing text, or say in the PR which ones are left behind.

## Layout

- `src/updates2mqtt/app.py`, `cli.py`, `config.py` - service entry point, CLI and configuration.
- `src/updates2mqtt/integrations/` - one module per update source (`docker.py`, `portainer.py`,
  `git_utils.py`) plus release-note enrichment (`docker_enrich.py`, `github_enrich.py`).
- `src/updates2mqtt/mqtt.py`, `hass_formatter.py` - MQTT publishing and the Home Assistant
  discovery payloads.

## Testing

Unit tests need no Docker engine or MQTT broker: the Docker client, paho MQTT client, HTTP calls
and subprocesses are mocked. Tests in
`tests/integration/` run against a disposable docker-in-docker engine, only with
`--integration`, and are skipped otherwise.

## Project Commands

- `uv sync --all-extras --dev` - install, as CI does
- `uv run pytest tests` - run unit tests (add `--integration` with a local Docker engine)
- `uv run ruff check --fix` - lint and auto-fix
- `uv run ruff format` - format code
- `uv run mypy src` - type check (CI also runs `ty check`)
- `uv run codespell` - spell check
- `pre-commit run` - check all staged files
- `uv run --group docs properdocs build` - build the documentation without starting a server

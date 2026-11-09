# Build

## Test

```bash
uv run pytest tests                                # unit tests only
uv run pytest tests --integration --runslow        # everything
```

Add `-o addopts=""` to skip the coverage and junit reports set in `pyproject.toml`.

### Unit Tests

Run with no flags, and need no Docker engine, MQTT broker or network access: the Docker client, MQTT client,
HTTP calls and subprocesses are all mocked. Anything that needs the network belongs under `--runslow`.

Settings the app reads from the environment, `MQTT_*`, `PORTAINER_*`, `U2M_*` and `NODE_NAME`, are cleared before
each test, so a shell set up to run the app doesn't change the config defaults the tests expect.

### Slow Tests

```bash
uv run pytest tests --runslow
```

Call real registries and release sources: Docker Hub, quay.io, GHCR, GitHub, GitLab and LinuxServer.io. They can
fail when one of those is down or rate limiting.

`test_github_enricher.py::test_pkg_enricher_live` also needs a GitHub token with `read:packages`, since GitHub's
packages API has no anonymous access, and is skipped without one:

```bash
GITHUB_TOKEN=$(gh auth token) uv run pytest tests/test_github_enricher.py::test_pkg_enricher_live --runslow
```

If `gh` lacks the scope, add it with `gh auth refresh -s read:packages`.

### Integration / Smoke Tests

```bash
uv run pytest tests/integration --integration
```

Need a local Docker engine, found through `DOCKER_HOST` or the default socket. The tests start a privileged
`docker:dind` container and run against that, so nothing touches the engine's own containers. Images pulled inside
it are kept in the `u2m-test-dind-cache` volume, which makes later runs faster.

- `test_image.py` builds the image from the `Dockerfile` and checks it starts, the only one CI runs, on pushes and
  PRs to `main`
- `test_dind_update.py` runs container updates end to end, through compose against a local registry and through
  Portainer, including a failed Portainer redeploy
- `PORTAINER_TEST_VERSIONS=2.45.0` limits the Portainer versions tested, by default 2.45.0 and 2.39.0

The integration fixtures set `DOCKER_CONFIG` for the whole session, so unit tests that read Docker client settings
from the environment must clear them first.

## Release

```bash
UV_NO_CONFIG=1 uv version 1.X.Y
```

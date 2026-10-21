#!/bin/bash
echo "Pull in auto bot PRs ..."
git pull
echo "Upgrading uv and friends ..."
mise upgrade
echo "Upgrading uv deps ..."
# --no-config + explicit flags: keep this project's lock isolated from any
# user-level ~/.config/uv/uv.toml (e.g. exclude-newer-package / prerelease
# settings for unrelated projects), which otherwise leaks into uv.lock.
# UV_NO_CONFIG also drops [tool.uv] from pyproject.toml, so its
# exclude-newer-package exemptions must be repeated here.
UV_NO_CONFIG=1 uv lock --upgrade --exclude-newer "5 days" \
    --exclude-newer-package certifi=false --exclude-newer-package pillow=false
echo "uv sync"
echo "Refreshing venv ..."
uv sync --dev --group docs
echo "Pre-commit autoupdate ..."
pre-commit autoupdate

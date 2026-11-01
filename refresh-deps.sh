#!/bin/bash
# Refresh this repo's tools and dependencies. Shared copy, kept in step by
# rhizomatics/.github scripts/sync-admin.sh: change it there, not here.
set -euo pipefail

echo "Pull in bot PRs ..."
git pull
echo "Upgrading uv and other mise tools ..."
mise upgrade

# Hide the user-level ~/.config/uv/uv.toml from uv, whose settings (e.g. exclude-newer-package
# entries for other projects) would otherwise be written into uv.lock and fail CI's --locked sync.
# Unlike --no-config / UV_NO_CONFIG, this keeps the project's own [tool.uv] settings.
# Both commands need it: a plain `uv sync` re-locks if the lock doesn't match the settings it sees.
project_uv() { XDG_CONFIG_HOME=/dev/null uv "$@"; }

echo "Upgrading uv deps ..."
project_uv lock --upgrade
echo "Refreshing venv ..."
project_uv sync --dev --group docs
echo "Pre-commit autoupdate ..."
pre-commit autoupdate

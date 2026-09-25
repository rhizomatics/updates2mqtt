#!/bin/bash
echo "Pull in auto bot PRs ..."
git pull
echo "Upgrading uv and friends ..."
mise upgrade
echo "Upgrading uv deps ..."
uv lock --upgrade
echo "Refreshing venv ..."
uv sync --dev --group docs
echo "Pre-commit autoupdate ..."
pre-commit autoupdate

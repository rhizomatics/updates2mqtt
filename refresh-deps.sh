#!/bin/bash
echo "Upgrading uv ..."
uv self update
echo "Upgrading uv deps ..."
uv lock --upgrade
echo "Pre-commit autoupdate ..."
pre-commit autoupdate

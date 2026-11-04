default: check

lint:
    uv run --locked ruff format --check
    uv run --locked ruff check --no-fix
    uv run --locked flake8 pylines_solid tests
    uv run --locked mypy
    uv run --locked auto-typing-final --check pylines_solid tests
    uv run --locked pylines-solid pylines_solid

test:
    uv run --locked pytest

check: lint test

build:
    uv build

smoke:
    #!/usr/bin/env bash
    set -euo pipefail
    package_directory="$(pwd)"
    temporary_directory="$(mktemp -d)"
    trap 'rm -rf "$temporary_directory"' EXIT
    uv venv "$temporary_directory/venv"
    uv pip install --python "$temporary_directory/venv/bin/python" dist/*.whl
    cd "$temporary_directory"
    "$temporary_directory/venv/bin/pylines-solid" "$package_directory/pylines_solid"

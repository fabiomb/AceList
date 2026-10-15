#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ ! -x .venv/bin/python ]]; then
    python_command=""
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 \
            && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
            python_command="$candidate"
            break
        fi
    done
    if [[ -z "$python_command" ]]; then
        echo "Hace falta Python 3.11 o superior." >&2
        exit 1
    fi
    echo "==> Creando el entorno virtual (.venv)"
    "$python_command" -m venv .venv
fi

marker=.venv/acelist-installed.txt
wanted="$(sha256sum pyproject.toml | cut -d ' ' -f 1)"
installed="$(test -f "$marker" && sed -n '1p' "$marker" || true)"
if [[ "$installed" != "$wanted" ]]; then
    echo "==> Instalando AceList y sus dependencias"
    .venv/bin/python -m pip install --disable-pip-version-check --quiet --editable .
    printf '%s\n' "$wanted" > "$marker"
fi

exec .venv/bin/python -m app.launcher "$@"

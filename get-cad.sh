#!/usr/bin/env bash
# TEXT-TO-SPACESHIP V3 (macOS / Linux / Codespaces): fetch the makers' CAD for the Builder's parts (docs/V3.md
# section 5.4) and import it through the app's checks; each file is used only when its SHA-256 is the recorded one.
# The files are the makers' (their licence terms apply): they stay in data/builder/cad, which git ignores.
# Usage: bash get-cad.sh [--from FOLDER] [--only PART ...] [--list] [--yes]                Needs uv.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "$here/tools/env.sh"
command -v uv >/dev/null || { echo "First run bash setup.sh (macOS), or install uv: https://docs.astral.sh/uv/"; exit 1; }
exec uv run --frozen --project "$here/backend" python "$here/backend/get_cad.py" "$@"

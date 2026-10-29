#!/usr/bin/env bash
# TEXT-TO-SPACESHIP V3: set this folder up on a Mac with Apple silicon (M1 or later), as setup.cmd does on Windows.
# Then start.sh starts the app and get-cad.sh fetches the makers' CAD. Everything goes into this folder: no
# administrator rights, nothing written to your user profile. Each download comes from its official site and is
# checked against the hash recorded in tools/toolchain.lock.json (SHA-256), backend/uv.lock (SHA-256, checked by uv)
# or frontend/package-lock.json (SHA-512, checked by npm):
#   tools/uv, tools/node    uv 0.12.23 and Node.js 24.21.0 (portable archives)
#   tools/python            CPython 3.14.8, through uv
#   backend/.venv           the Python packages pinned in backend/uv.lock
#   tools/ccx, tools/beso   CalculiX 2.23 and BESO (backend/setup_fea.py)
#   frontend/dist           the user interface, from frontend/package-lock.json
# Run it again at any time (after an update, say): what is in place is checked and kept.
# Usage: bash setup.sh [--yes]     --yes: no questions, and no makers' CAD (get-cad.sh fetches that)
set -euo pipefail
cd "$(dirname "$0")"
. tools/env.sh
YES=0
[ "${1:-}" = "--yes" ] && YES=1

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "setup.sh is for macOS on Apple silicon. Elsewhere: install uv and Node.js 24, then run bash start.sh."
  exit 1
fi

stop() {
  echo
  echo "Setup stopped: see the message above. Once that is solved, run setup.sh again: it keeps what is done."
  exit 1
}

check() {   # check FILE SHA256: true when FILE exists and has this SHA-256
  [ -f "$1" ] && [ "$(shasum -a 256 "$1" | cut -d' ' -f1)" = "$2" ]
}

fetch() {   # fetch URL NAME SHA256: tools/downloads/NAME kept when it has this SHA-256, else downloaded and checked
  local file="tools/downloads/$2"
  check "$file" "$3" && return 0
  mkdir -p tools/downloads
  echo "Downloading $1"
  if ! curl -fL --retry 2 --proto =https --proto-redir =https -o "$file.part" "$1"; then
    rm -f "$file.part"
    echo "Download failed: $1"
    return 1
  fi
  if ! check "$file.part" "$3"; then
    rm -f "$file.part"
    echo "Not the recorded file (its SHA-256 differs), so not used: $1"
    return 1
  fi
  mv -f "$file.part" "$file"
}

echo "TEXT-TO-SPACESHIP V3 setup, into $PWD"
echo "It downloads what is not here yet, each file checked against its recorded hash:"
echo "  uv 0.12.23 (17 MB, github.com/astral-sh/uv) and Node.js 24.21.0 (53 MB, nodejs.org)"
echo "  CPython 3.14.8 (through uv) and the Python packages of backend/uv.lock (pypi.org)"
echo "  the JavaScript packages of frontend/package-lock.json (registry.npmjs.org)"
echo "  CalculiX 2.23 (7 packages, 7 MB, conda.anaconda.org) and BESO (22 MB, github.com/calculix/beso)"
echo "About 2.5 GB of disk once set up."
if [ $YES -eq 0 ]; then
  read -r -p "Continue [Y/N]? " a
  case "$a" in [Yy]*) ;; *) exit 1 ;; esac
fi

if [ ! -x tools/uv/uv ]; then
  fetch https://github.com/astral-sh/uv/releases/download/0.12.23/uv-aarch64-apple-darwin.tar.gz uv-aarch64-apple-darwin.tar.gz 50487ae565ccd96e499056b4674d438f4c53170202617b4c759defe0c6a1b544 || stop
  mkdir -p tools/uv
  tar -xzf tools/downloads/uv-aarch64-apple-darwin.tar.gz -C tools/uv --strip-components=1 || stop
fi
if [ ! -x tools/node/bin/node ]; then
  fetch https://nodejs.org/dist/v24.21.0/node-v24.21.0-darwin-arm64.tar.gz node-v24.21.0-darwin-arm64.tar.gz bed7eea5325e1108f32ce5228ddd6a5f0f08a499ee42aa7442aea583702f6057 || stop
  mkdir -p tools/node
  tar -xzf tools/downloads/node-v24.21.0-darwin-arm64.tar.gz -C tools/node --strip-components=1 || stop
fi

echo
echo "CPython 3.14.8 and the Python packages:"
(
  cd backend
  uv python install 3.14.8
  uv sync --frozen
  echo
  uv run --frozen python setup_fea.py
  echo
  echo "Checking the Python packages:"
  uv run --frozen python tools_smoke.py
) || stop

echo
echo "The user interface:"
(cd frontend && npm ci --no-audit --no-fund && npm run build) || stop

echo
echo "Setup done. bash start.sh starts the app at http://127.0.0.1:8768/"
echo "The makers' CAD is not in the repository: bash get-cad.sh fetches it from the makers' sites (14 files, 148.7 MB)."
[ $YES -eq 1 ] && exit 0
read -r -p "Fetch the makers' CAD now [Y/N]? " a
case "$a" in [Yy]*) exec bash get-cad.sh --yes ;; esac

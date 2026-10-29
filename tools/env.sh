# Session-only environment for the project toolchain (macOS / Linux), as tools/env.cmd on Windows: uv's cache and
# Pythons, npm's cache and Playwright's browsers stay inside tools/; the portable uv and Node.js that setup.sh puts in
# tools/ come first on PATH, installed ones after. Nothing is written to the user profile.
# Usage (bash or zsh):  . /path/to/text-to-spaceship/tools/env.sh
T2S_TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
T2S_ROOT="$(cd "$T2S_TOOLS/.." && pwd)"
export T2S_TOOLS T2S_ROOT
export UV_CACHE_DIR="$T2S_TOOLS/cache/uv"
export UV_PYTHON_INSTALL_DIR="$T2S_TOOLS/python"
export UV_PYTHON_CACHE_DIR="$T2S_TOOLS/cache/uv-python"
export UV_PYTHON_BIN_DIR="$T2S_TOOLS/bin"
export UV_TOOL_DIR="$T2S_TOOLS/uv-tools"
export UV_TOOL_BIN_DIR="$T2S_TOOLS/bin"
export UV_PYTHON_INSTALL_BIN=0
export UV_PYTHON_PREFERENCE=only-managed
export UV_NO_MODIFY_PATH=1
export npm_config_cache="$T2S_TOOLS/cache/npm"
export npm_config_prefix="$T2S_TOOLS/npm-global"
export npm_config_update_notifier=false
export PLAYWRIGHT_BROWSERS_PATH="$T2S_TOOLS/ms-playwright"
export NUMBA_CACHE_DIR="$T2S_TOOLS/cache/numba"
export PYTHONUTF8=1
export PATH="$T2S_TOOLS/uv:$T2S_TOOLS/node/bin:$T2S_TOOLS/bin:$HOME/.local/bin:$PATH"

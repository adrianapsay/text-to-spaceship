# Session-only environment for the project toolchain. Nothing is written to the
# registry or the user profile. Usage (PowerShell):  . D:\text-to-spaceship\tools\env.ps1
$T2S_ROOT = Split-Path -Parent $PSScriptRoot
$T2S_TOOLS = $PSScriptRoot
$env:T2S_ROOT = $T2S_ROOT
$env:UV_CACHE_DIR = "$T2S_TOOLS\cache\uv"
$env:UV_PYTHON_INSTALL_DIR = "$T2S_TOOLS\python"
$env:UV_PYTHON_CACHE_DIR = "$T2S_TOOLS\cache\uv-python"
$env:UV_PYTHON_BIN_DIR = "$T2S_TOOLS\bin"
$env:UV_TOOL_DIR = "$T2S_TOOLS\uv-tools"
$env:UV_TOOL_BIN_DIR = "$T2S_TOOLS\bin"
$env:UV_PYTHON_INSTALL_BIN = "0"
$env:UV_PYTHON_INSTALL_REGISTRY = "0"
$env:UV_PYTHON_NO_REGISTRY = "1"
$env:UV_PYTHON_PREFERENCE = "only-managed"
$env:UV_NO_MODIFY_PATH = "1"
$env:npm_config_cache = "$T2S_TOOLS\cache\npm"
$env:npm_config_prefix = "$T2S_TOOLS\npm-global"
$env:npm_config_update_notifier = "false"
$env:PLAYWRIGHT_BROWSERS_PATH = "$T2S_TOOLS\ms-playwright"
$env:GIT_CONFIG_GLOBAL = "$T2S_TOOLS\gitconfig"
$env:GIT_CONFIG_NOSYSTEM = "1"
$env:NUMBA_CACHE_DIR = "$T2S_TOOLS\cache\numba"
$env:PYTHONUTF8 = "1"
$env:PATH = "$T2S_TOOLS\uv;$T2S_TOOLS\node;$T2S_TOOLS\mingit\cmd;$T2S_TOOLS\bin;$env:PATH"

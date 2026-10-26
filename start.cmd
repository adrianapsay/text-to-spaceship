@echo off
rem TEXT-TO-SPACESHIP: build the UI if needed, start the backend on http://127.0.0.1:8768 and open it.
rem Usage: start.cmd [--project NAME] [--add C:\path\friend_part.stl ...]
rem Needs uv and Node.js 24: the project's portable copies in tools\ when present, otherwise installed ones.
setlocal
call "%~dp0tools\env.cmd" || exit /b 1
where uv >nul 2>nul || (echo uv is required: https://docs.astral.sh/uv/getting-started/installation/ & exit /b 1)
where npm >nul 2>nul || (echo Node.js 24 is required: https://nodejs.org/ & exit /b 1)
if not exist "%~dp0frontend\dist\index.html" (
  echo Building the user interface...
  pushd "%~dp0frontend" || exit /b 1
  if not exist node_modules (call npm ci || exit /b 1)
  call npm run build || exit /b 1
  popd
)
start "" http://127.0.0.1:8768/
cd /d "%~dp0backend"
uv run python run_server.py %*

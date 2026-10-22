@echo off
rem TEXT-TO-SPACESHIP: build the UI if needed, start the backend on http://127.0.0.1:8765 and open it.
rem Usage: start.cmd [--project NAME] [--add C:\path\friend_part.stl ...]
setlocal
call "%~dp0tools\env.cmd" || exit /b 1
if not exist "%~dp0frontend\dist\index.html" (
  echo Building the user interface...
  pushd "%~dp0frontend" && call npm run build && popd || exit /b 1
)
start "" http://127.0.0.1:8765/
cd /d "%~dp0backend"
uv run python run_server.py %*

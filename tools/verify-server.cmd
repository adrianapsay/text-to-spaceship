@echo off
rem V3 verification server: project v3verify on port 8769, no automatic search (for checks of the app).
call "%~dp0env.cmd" || exit /b 1
cd /d "%~dp0..\backend"
uv run python run_server.py --project v3verify --port 8769 --islands 2 --no-search

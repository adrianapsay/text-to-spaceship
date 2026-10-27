@echo off
rem TEXT-TO-SPACESHIP V3: set this folder up on a 64-bit Windows 10 (version 1803 or later) or Windows 11 PC. Then
rem start.cmd starts the app and get-cad.cmd fetches the makers' CAD. Everything goes into this folder: no
rem administrator rights, nothing written to the registry or to your user profile. Each download comes from its
rem official site and is checked against the hash recorded in tools\toolchain.lock.json (SHA-256), backend\uv.lock
rem (SHA-256, checked by uv) or frontend\package-lock.json (SHA-512, checked by npm):
rem   tools\uv, tools\node    uv 0.12.23 and Node.js 24.21.0 (portable zips)
rem   tools\python            CPython 3.14.8, through uv
rem   backend\.venv           the Python packages pinned in backend\uv.lock
rem   tools\ccx, tools\beso   CalculiX 2.23 and BESO (backend\setup_fea.py)
rem   frontend\dist           the user interface, from frontend\package-lock.json
rem Run it again at any time (after an update, say): what is in place is checked and kept.
rem Usage: setup.cmd [--yes]     --yes: no questions, and no makers' CAD (get-cad.cmd fetches that)
setlocal
cd /d "%~dp0"
call tools\env.cmd || exit /b 1
set "SYS=%SystemRoot%\System32"
for %%x in (curl.exe tar.exe certutil.exe choice.exe) do if not exist "%SYS%\%%x" (
  echo setup.cmd needs Windows 10 version 1803 or later: %%x is missing.
  goto :stop
)
echo TEXT-TO-SPACESHIP V3 setup, into %CD%
echo It downloads what is not here yet, each file checked against its recorded hash:
echo   uv 0.12.23 (18 MB, github.com/astral-sh/uv) and Node.js 24.21.0 (38 MB, nodejs.org)
echo   CPython 3.14.8 (23 MB, through uv) and the Python packages of backend\uv.lock (pypi.org)
echo   the JavaScript packages of frontend\package-lock.json (registry.npmjs.org)
echo   CalculiX 2.23 (9 packages, 10 MB, conda.anaconda.org) and BESO (22 MB, github.com/calculix/beso)
echo About 2.5 GB of disk once set up.
if /i not "%~1"=="--yes" (
  "%SYS%\choice.exe" /c YN /m "Continue"
  if errorlevel 2 exit /b 1
)

if not exist tools\uv\uv.exe (
  call :fetch https://github.com/astral-sh/uv/releases/download/0.12.23/uv-x86_64-pc-windows-msvc.zip uv-x86_64-pc-windows-msvc.zip 75d05de6762778c31ee183398de7dd15093fad0ed90b1f236d8205ea5ec00c90 || goto :stop
  if not exist tools\uv mkdir tools\uv
  "%SYS%\tar.exe" -xf tools\downloads\uv-x86_64-pc-windows-msvc.zip -C tools\uv || goto :stop
)
if not exist tools\node\node.exe (
  call :fetch https://nodejs.org/dist/v24.21.0/node-v24.21.0-win-x64.zip node-v24.21.0-win-x64.zip 158f7685b44de51f6c0df1d153526cbcd3e1bc739a8dfc607721cef75de9e541 || goto :stop
  if not exist tools\node mkdir tools\node
  "%SYS%\tar.exe" -xf tools\downloads\node-v24.21.0-win-x64.zip -C tools\node --strip-components=1 || goto :stop
)

echo.
echo CPython 3.14.8 and the Python packages:
pushd backend
uv python install 3.14.8 || goto :failed
uv sync --frozen || goto :failed
echo.
uv run --frozen python setup_fea.py || goto :failed
echo.
echo Checking the Python packages:
uv run --frozen python tools_smoke.py || goto :failed
popd

echo.
echo The user interface:
pushd frontend
call npm ci --no-audit --no-fund || goto :failed
call npm run build || goto :failed
popd

echo.
echo Setup done. start.cmd starts the app at http://127.0.0.1:8768/
echo The makers' CAD is not in the repository: get-cad.cmd fetches it from the makers' sites (14 files, 148.7 MB).
if /i "%~1"=="--yes" exit /b 0
"%SYS%\choice.exe" /c YN /m "Fetch the makers' CAD now"
if errorlevel 2 (
  pause
  exit /b 0
)
call get-cad.cmd --yes
pause
exit /b 0

:failed
popd
:stop
echo.
echo Setup stopped: see the message above. Once that is solved, run setup.cmd again: it keeps what is done.
if /i not "%~1"=="--yes" pause
exit /b 1

:fetch
rem call :fetch URL NAME SHA256: tools\downloads\NAME is kept when it already has this SHA-256; otherwise it is
rem downloaded (HTTPS only, redirects too) and checked, and a download that is not the recorded file is deleted.
set "FILE=tools\downloads\%~2"
call :check "%FILE%" %3 && exit /b 0
if not exist tools\downloads mkdir tools\downloads
echo Downloading %~1
"%SYS%\curl.exe" -fL --retry 2 --proto =https --proto-redir =https -o "%FILE%.part" %1
if errorlevel 1 (
  del "%FILE%.part" 2>nul
  echo Download failed: %~1
  exit /b 1
)
call :check "%FILE%.part" %3
if errorlevel 1 (
  del "%FILE%.part"
  echo Not the recorded file ^(its SHA-256 differs^), so not used: %~1
  exit /b 1
)
move /y "%FILE%.part" "%FILE%" >nul
exit /b 0

:check
rem call :check FILE SHA256: errorlevel 0 when FILE exists and has this SHA-256.
if not exist "%~1" exit /b 1
set "GOT="
for /f "skip=1 delims=" %%h in ('certutil -hashfile "%~1" SHA256') do if not defined GOT set "GOT=%%h"
if not defined GOT exit /b 1
set "GOT=%GOT: =%"
if /i "%GOT%"=="%~2" exit /b 0
exit /b 1

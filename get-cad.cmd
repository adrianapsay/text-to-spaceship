@echo off
rem TEXT-TO-SPACESHIP V3: fetch the makers' CAD for the Builder's parts (docs\V3.md section 5.4) and import it through
rem the app's checks. Each file comes from its maker's site (or, with --from FOLDER, from a copy of
rem data\builder\cad\downloads made on another computer) and is used only when its SHA-256 is the recorded one. The
rem files are the makers' (their licence terms apply): they stay in data\builder\cad, which git ignores.
rem Usage: get-cad.cmd [--from FOLDER] [--only PART ...] [--list] [--yes]
setlocal
call "%~dp0tools\env.cmd" || exit /b 1
where uv >nul 2>nul || (echo Run setup.cmd first: it sets up what this needs. & pause & exit /b 1)
uv run --frozen --project "%~dp0backend" python "%~dp0backend\get_cad.py" %*
set "RC=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %RC%

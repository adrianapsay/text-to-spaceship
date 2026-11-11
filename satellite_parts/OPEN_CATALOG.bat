@echo off
rem Opens the local Satellite Parts Catalog (rebuilds it from the part folders first if anything changed).
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (python catalog_local.py %*) else ("C:\Users\danie\AppData\Local\Python\pythoncore-3.14-64\python.exe" catalog_local.py %*)
if errorlevel 1 pause

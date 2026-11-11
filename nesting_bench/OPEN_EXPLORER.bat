@echo off
rem Opens the local Nesting Bench Explorer (rebuilds it from results\ first if anything changed).
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (python explorer_local.py %*) else ("C:\Users\danie\AppData\Local\Python\pythoncore-3.14-64\python.exe" explorer_local.py %*)
if errorlevel 1 pause

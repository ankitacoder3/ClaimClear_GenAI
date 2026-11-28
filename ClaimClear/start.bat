@echo off
rem ClaimClear in one command (Windows CMD): installs on first run, starts the servers, opens the web UI.
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython
%PY% start.py %*
exit /b %errorlevel%
:nopython
echo Python is needed to start ^(any version 3.8 or newer^): install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and run start.bat again.
exit /b 1

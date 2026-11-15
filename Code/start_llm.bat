@echo off
rem Start a local LLM for ClaimClear and choose its model (Windows CMD). Then run start.bat.
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython
%PY% start_llm.py %*
exit /b %errorlevel%
:nopython
echo Python is needed to start ^(any version 3.8 or newer^): install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and run start_llm.bat again.
exit /b 1

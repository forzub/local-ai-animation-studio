@echo off
rem Local AI Studio: one-click launcher
cd /d "%~dp0"
set PYTHONUTF8=1
set PY=D:\Miniconda\envs\ai-studio\python.exe
if not exist "%PY%" (
  echo Python environment ai-studio not found: %PY%
  pause
  exit /b 1
)
"%PY%" -m studio %*
if errorlevel 1 pause

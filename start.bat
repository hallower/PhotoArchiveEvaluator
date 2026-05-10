@echo off
REM Photo Archive Evaluator launcher (Windows).
REM
REM Usage:
REM   start.bat            : build frontend if dist missing, then run uvicorn
REM   start.bat --rebuild  : force frontend rebuild
REM
REM Env vars:
REM   PAE_HOST  bind host (default 0.0.0.0 -- LAN access)
REM   PAE_PORT  bind port (default 8770)
REM
REM First-time setup (run once):
REM   python -m venv backend\.venv
REM   backend\.venv\Scripts\pip install -e backend
REM   cd frontend ^&^& npm install

REM Switch console to UTF-8 so any non-ASCII output renders correctly.
chcp 65001 >nul

setlocal enabledelayedexpansion

REM Move to script directory so it works from any cwd.
cd /d "%~dp0"

REM 1. backend venv check
if not exist "backend\.venv\Scripts\python.exe" (
  echo ERROR: backend\.venv not found. Run setup first: 1>&2
  echo   python -m venv backend\.venv 1>&2
  echo   backend\.venv\Scripts\pip install -e backend 1>&2
  exit /b 1
)

REM 2. frontend node_modules check (auto-install if missing)
if not exist "frontend\node_modules" (
  echo [setup] installing frontend dependencies ^(npm install^)...
  pushd frontend
  call npm install
  if errorlevel 1 (
    popd
    echo ERROR: npm install failed 1>&2
    exit /b 1
  )
  popd
)

REM 3. frontend dist build -- when missing or --rebuild
set REBUILD=0
if "%~1"=="--rebuild" set REBUILD=1
if not exist "frontend\dist\index.html" set REBUILD=1
if "%REBUILD%"=="1" (
  echo [build] building frontend...
  pushd frontend
  call npm run build
  if errorlevel 1 (
    popd
    echo ERROR: npm run build failed 1>&2
    exit /b 1
  )
  popd
)

REM 4. run uvicorn
if "%PAE_HOST%"=="" set PAE_HOST=0.0.0.0
if "%PAE_PORT%"=="" set PAE_PORT=8770
echo [run] http://%PAE_HOST%:%PAE_PORT%   ^(Ctrl+C to stop^)
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host %PAE_HOST% --port %PAE_PORT%

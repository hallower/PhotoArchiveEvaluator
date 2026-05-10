@echo off
REM Photo Archive Evaluator launcher (Windows). See --help.

REM Switch console to UTF-8 so any non-ASCII output renders correctly.
chcp 65001 >nul

setlocal enabledelayedexpansion

REM Move to script directory so it works from any cwd.
cd /d "%~dp0"

REM ── Parse args ───────────────────────────────────────────────
set DO_BUILD=1
set RESCORE_DOC=0
set RESCORE_PROMPT=0

:parse_args
if "%~1"=="" goto end_parse
if /i "%~1"=="--help" goto show_help
if /i "%~1"=="-h" goto show_help
if /i "%~1"=="/?" goto show_help
if /i "%~1"=="--no-build" (set DO_BUILD=0) & goto next_arg
if /i "%~1"=="--rescore-doc" (set RESCORE_DOC=1) & goto next_arg
if /i "%~1"=="--rescore-prompt" (set RESCORE_PROMPT=1) & goto next_arg
echo ERROR: unknown argument: %~1 1>&2
echo run "start.bat --help" to see options 1>&2
exit /b 2
:next_arg
shift
goto parse_args
:end_parse

REM ── 1. backend venv check ────────────────────────────────────
if not exist "backend\.venv\Scripts\python.exe" (
  echo ERROR: backend\.venv not found. Run setup first: 1>&2
  echo   python -m venv backend\.venv 1>&2
  echo   backend\.venv\Scripts\pip install -e backend 1>&2
  exit /b 1
)

REM ── 2. frontend node_modules ─────────────────────────────────
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

REM ── 3. frontend build (default; skip with --no-build) ────────
if "%DO_BUILD%"=="1" (
  echo [build] building frontend...
  pushd frontend
  call npm run build
  if errorlevel 1 (
    popd
    echo ERROR: npm run build failed 1>&2
    exit /b 1
  )
  popd
) else (
  if not exist "frontend\dist\index.html" (
    echo ERROR: --no-build but frontend\dist\index.html missing. Run without --no-build first. 1>&2
    exit /b 1
  )
  echo [build] skipped ^(--no-build^)
)

REM ── 4. optional rescore tasks (one-shot, before uvicorn) ─────
if "%RESCORE_DOC%"=="1" (
  echo [rescore] documentary coverage ^(may load CLIP model ~10s^)...
  pushd backend
  .\.venv\Scripts\python.exe -c "from app.evaluator.rescore import ensure_documentary_coverage; from app.storage.db import SessionLocal; print('  result:', ensure_documentary_coverage(SessionLocal))"
  if errorlevel 1 (
    popd
    echo ERROR: ensure_documentary_coverage failed 1>&2
    exit /b 1
  )
  popd
)
if "%RESCORE_PROMPT%"=="1" (
  echo [rescore] prompt CLIP scores ^(may load CLIP model ~10s^)...
  pushd backend
  .\.venv\Scripts\python.exe -c "from app.evaluator.rescore import rescore_prompt; from app.storage.db import SessionLocal; print('  added rows:', rescore_prompt(SessionLocal))"
  if errorlevel 1 (
    popd
    echo ERROR: rescore_prompt failed 1>&2
    exit /b 1
  )
  popd
)

REM ── 5. uvicorn ───────────────────────────────────────────────
if "%PAE_HOST%"=="" set PAE_HOST=0.0.0.0
if "%PAE_PORT%"=="" set PAE_PORT=8770
echo [run] http://%PAE_HOST%:%PAE_PORT%   ^(Ctrl+C to stop^)
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host %PAE_HOST% --port %PAE_PORT%
exit /b %ERRORLEVEL%

REM ── help ─────────────────────────────────────────────────────
:show_help
echo.
echo Photo Archive Evaluator launcher
echo.
echo Usage:
echo   start.bat [options]
echo.
echo Options:
echo   --help, -h, /?       Show this help and exit.
echo   --no-build           Skip frontend build (uses existing dist; faster restart).
echo   --rescore-doc        Ensure all active photos have documentary scores:
echo                          - photos with CLIP embedding: rescored immediately
echo                          - photos without embedding: queued as basic eval jobs
echo                            (worker will compute doc score during processing)
echo                        Use after first installing the documentary feature or
echo                        after changing the documentary prompt in Settings.
echo   --rescore-prompt     Backfill prompt CLIP scores. Use after changing the
echo                        eval prompt in Settings.
echo.
echo Environment variables:
echo   PAE_HOST   bind host (default 0.0.0.0; LAN access)
echo   PAE_PORT   bind port (default 8770)
echo.
echo Examples:
echo   start.bat
echo   start.bat --no-build
echo   start.bat --rescore-doc
echo   start.bat --rescore-doc --no-build
echo.
echo First-time setup (one-shot):
echo   python -m venv backend\.venv
echo   backend\.venv\Scripts\pip install -e backend
echo   pushd frontend ^&^& npm install ^&^& popd
echo.
exit /b 0

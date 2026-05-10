#!/usr/bin/env bash
#
# Photo Archive Evaluator 단일 명령 런처 (Linux / macOS / WSL).
#
# 사용:
#   ./start.sh              # frontend dist 없으면 빌드, uvicorn 실행
#   ./start.sh --rebuild    # frontend 강제 재빌드 후 실행
#
# 환경변수:
#   PAE_HOST  바인드 호스트 (기본: 0.0.0.0 — LAN 접근 허용)
#   PAE_PORT  바인드 포트   (기본: 8770)
#
# 사전 준비 (최초 1회):
#   python3 -m venv backend/.venv
#   backend/.venv/bin/pip install -e backend
#   cd frontend && npm install

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# 1. backend 가상환경 확인
if [ ! -x "backend/.venv/bin/python" ]; then
  echo "ERROR: backend/.venv 가 없습니다. 다음을 먼저 실행하세요:" >&2
  echo "  python3 -m venv backend/.venv" >&2
  echo "  backend/.venv/bin/pip install -e backend" >&2
  exit 1
fi

# 2. frontend node_modules 확인 (없으면 자동 설치)
if [ ! -d "frontend/node_modules" ]; then
  echo "[setup] frontend 의존성 설치 (npm install)…"
  (cd frontend && npm install)
fi

# 3. frontend dist 빌드 — 없거나 --rebuild 시
if [ "${1:-}" = "--rebuild" ] || [ ! -f "frontend/dist/index.html" ]; then
  echo "[build] frontend 빌드…"
  (cd frontend && npm run build)
fi

# 4. uvicorn 실행
HOST="${PAE_HOST:-0.0.0.0}"
PORT="${PAE_PORT:-8770}"
echo "[run] http://${HOST}:${PORT}  (Ctrl+C 로 종료)"
cd backend
exec ./.venv/bin/python -m uvicorn app.main:app --host "${HOST}" --port "${PORT}"

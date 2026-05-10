#!/usr/bin/env bash
#
# Photo Archive Evaluator launcher (Linux / macOS / WSL).
# Run "./start.sh --help" for usage.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

show_help() {
  cat <<'EOF'

Photo Archive Evaluator launcher

Usage:
  ./start.sh [options]

Options:
  --help, -h           이 도움말을 보고 종료.
  --no-build           frontend 빌드 건너뜀 (기존 dist 사용; 빠른 재기동).
  --rescore-doc        모든 active 사진에 documentary 점수 보장:
                         - 임베딩 있는 사진: 즉시 cosine으로 점수 추가
                         - 임베딩 없는 사진: basic eval 잡으로 큐잉 (워커가 처리)
                       다큐 기능 처음 설치 후, 또는 documentary prompt 변경 후 사용.
  --rescore-prompt     prompt CLIP 점수 백필. 설정에서 eval prompt를 바꾼 뒤 사용.
  --scan               서버 시작 후 저장된 폴더를 자동 재스캔. DB에 등록된 모든
                       사진의 부모 폴더를 walk해 새 사진을 발견하면 평가 큐에 등록.

Env vars:
  PAE_HOST   바인드 호스트 (기본 0.0.0.0 — LAN 접근)
  PAE_PORT   바인드 포트   (기본 8770)

Examples:
  ./start.sh
  ./start.sh --no-build
  ./start.sh --rescore-doc
  ./start.sh --rescore-doc --no-build

First-time setup (one-shot):
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -e backend
  (cd frontend && npm install)

EOF
}

# ── 인자 파싱 ─────────────────────────────────────────────────
DO_BUILD=1
RESCORE_DOC=0
RESCORE_PROMPT=0
DO_SCAN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) show_help; exit 0 ;;
    --no-build) DO_BUILD=0 ;;
    --rescore-doc) RESCORE_DOC=1 ;;
    --rescore-prompt) RESCORE_PROMPT=1 ;;
    --scan) DO_SCAN=1 ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      echo 'run "./start.sh --help" to see options' >&2
      exit 2
      ;;
  esac
  shift
done

# ── 1. backend venv 확인 ─────────────────────────────────────
if [ ! -x "backend/.venv/bin/python" ]; then
  echo "ERROR: backend/.venv 가 없습니다. 다음을 먼저 실행하세요:" >&2
  echo "  python3 -m venv backend/.venv" >&2
  echo "  backend/.venv/bin/pip install -e backend" >&2
  exit 1
fi

# ── 2. frontend node_modules ─────────────────────────────────
if [ ! -d "frontend/node_modules" ]; then
  echo "[setup] frontend 의존성 설치 (npm install)…"
  (cd frontend && npm install)
fi

# ── 3. frontend 빌드 (기본; --no-build로 건너뜀) ─────────────
if [ "$DO_BUILD" -eq 1 ]; then
  echo "[build] frontend 빌드…"
  (cd frontend && npm run build)
else
  if [ ! -f "frontend/dist/index.html" ]; then
    echo "ERROR: --no-build 인데 frontend/dist 가 없습니다. 처음 1회는 인자 없이 실행하세요." >&2
    exit 1
  fi
  echo "[build] 건너뜀 (--no-build)"
fi

# ── 4. 선택적 rescore (uvicorn 시작 전 1회) ─────────────────
if [ "$RESCORE_DOC" -eq 1 ]; then
  echo "[rescore] documentary coverage (CLIP 모델 ~10초 로드)…"
  (cd backend && ./.venv/bin/python -c "
from app.evaluator.rescore import ensure_documentary_coverage
from app.storage.db import SessionLocal
print('  result:', ensure_documentary_coverage(SessionLocal))
")
fi
if [ "$RESCORE_PROMPT" -eq 1 ]; then
  echo "[rescore] prompt CLIP 점수 (CLIP 모델 ~10초 로드)…"
  (cd backend && ./.venv/bin/python -c "
from app.evaluator.rescore import rescore_prompt
from app.storage.db import SessionLocal
print('  added rows:', rescore_prompt(SessionLocal))
")
fi

# ── 5. uvicorn ───────────────────────────────────────────────
HOST="${PAE_HOST:-0.0.0.0}"
PORT="${PAE_PORT:-8770}"
if [ "$DO_SCAN" -eq 1 ]; then
  echo "[scan] PAE_AUTOSCAN=1 — 서버 시작 후 저장된 폴더 자동 재스캔"
  export PAE_AUTOSCAN=1
fi
echo "[run] http://${HOST}:${PORT}  (Ctrl+C 로 종료)"
cd backend
exec ./.venv/bin/python -m uvicorn app.main:app --host "${HOST}" --port "${PORT}"

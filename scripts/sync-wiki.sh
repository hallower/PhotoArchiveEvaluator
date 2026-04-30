#!/usr/bin/env bash
#
# docs/ → GitHub Wiki 수동 동기화 스크립트
#
# 전제: GitHub 저장소의 Wiki가 초기화되어 있어야 한다 (웹 UI에서 첫 페이지 생성).
#
# 사용법:
#   bash scripts/sync-wiki.sh

set -euo pipefail

REPO_SSH="git@github.com:hallower/PhotoArchiveEvaluator.wiki.git"
WORKDIR="$(mktemp -d)"
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)/docs"

trap 'rm -rf "$WORKDIR"' EXIT

echo "[*] Cloning wiki: $REPO_SSH"
git clone --depth=1 "$REPO_SSH" "$WORKDIR/wiki"

echo "[*] Copying docs/*.md → wiki/"
# 위키는 평면 구조(폴더 미지원). docs/의 *.md 만 복사.
cp "$SRC_DIR"/*.md "$WORKDIR/wiki/"

cd "$WORKDIR/wiki"
git add -A

if git diff --cached --quiet; then
  echo "[=] No changes. Done."
  exit 0
fi

git commit -m "docs: sync from main repo $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git push origin master

echo "[+] Wiki updated."

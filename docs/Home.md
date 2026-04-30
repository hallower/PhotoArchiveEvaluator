# Photo Archive Evaluator — Wiki

NAS에 저장된 사진을 자동으로 인식·평가하여 포트폴리오 구성, 주제별 정리, 공모전
출품 후보 선별을 돕는 도구.

---

## 문서 구성

| 문서 | 내용 |
|---|---|
| [SPEC](SPEC) | 전체 명세서 — 목적, 시나리오, 기능·비기능 요구사항, AI 모델, 성공 기준 |
| [MVP](MVP) | 4단계 점진 확장 계획과 단계별 검증 기준 |
| [ARCHITECTURE](ARCHITECTURE) | 시스템 구성, 컴포넌트, 디렉터리, 데이터 흐름, 기술 스택 |
| [SCHEMA](SCHEMA) | DB 스키마, DDL, 인덱스, 제약, 마이그레이션 정책 |
| [POC_REPORT](POC_REPORT) | Phase 1 PoC 측정 결과 (속도, 점수 분포, 정규화 결정) |
| [USAGE](USAGE) | **실행 방법 / 일상 사용** — 설치·DB·UI·CLI·트러블슈팅 |

---

## 빠른 요약

- **대상**: 1인 사용자, Synology DS218+ + Windows PC(RTX 4050) 환경
- **언어/스택**: Python 3.11 + FastAPI + SQLite + React/Vite, AI는 ONNX Runtime
- **1차 범위**: JPG만, local 미학 모델, 단일 폴더, 수동 스캔
- **저장 정책**: 모든 평가 결과 저장. 표시 임계값(기본 4점)으로 필터
- **백업**: PC 메인 + NAS 주기 백업, UI에서 복원

## 변경 이력

본 위키는 메인 저장소의 [`docs/`](https://github.com/hallower/PhotoArchiveEvaluator/tree/main/docs)
폴더에서 자동 동기화된다. 변경은 PR로 검토 → main 머지 → 위키 반영 순서로 흐른다.

# 아키텍처

## 1. 시스템 구성

```
┌──────────────────────────────────────────────────────────┐
│  PC (Windows / Linux)                                    │
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │  Backend Service (단일 프로세스, OS service)       │ │
│  │                                                    │ │
│  │   FastAPI ── 정적 웹 UI / REST API                 │ │
│  │   Scheduler (APScheduler)                          │ │
│  │   ScannerWorker × 1                                │ │
│  │   EvaluatorWorker × N (asyncio)                    │ │
│  │   AI Adapters (local / remote)                     │ │
│  │   Storage (SQLite + sqlite-vec + thumbnail cache)  │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  GPU: RTX 4050 6GB (ONNX Runtime + DirectML / CUDA)      │
└──────────────────────────────────────────────────────────┘
        │                          ▲
        │ DSM FileStation          │ HTTPS (옵션)
        ▼                          │
┌──────────────────┐       ┌────────────────────────────┐
│  NAS (DS218+)    │       │  External AI APIs          │
│                  │       │  Claude / GPT / Gemini     │
│  사진 원본       │       └────────────────────────────┘
│  /backup         │
│   ├─ db.dump     │
│   ├─ embeddings/ │
│   └─ thumbs/     │
└──────────────────┘
```

## 2. 컴포넌트

### 2.1 Backend Service (FastAPI, Python 3.11+)
- HTTP API
- 정적 웹 UI 서빙
- 비밀번호 인증(bcrypt + 세션 쿠키)
- 모든 워커가 같은 프로세스의 asyncio 큐 공유

### 2.2 Scheduler (APScheduler)
- 요일/시간 cron 트리거
- 절전·복귀 감지(Windows: power events / Linux: systemd suspend hook)

### 2.3 NAS Client
- Synology DSM FileStation 어댑터(REST)
- 세션 쿠키 / API 토큰 관리, 만료 자동 재로그인
- 자격증명 OS 키체인 보관

### 2.4 Worker Pool
- **ScannerWorker** (1): 폴더 walk → 후보 큐 적재
- **EvaluatorWorker** (N): 후보 큐 → 모델 호출 → DB 저장
- 동시성 상한 / rate limit 가드(token bucket)
- 작업 단위 트랜잭션, 재개

### 2.5 AI Adapter Layer

```python
# backend/app/ai/base.py 의 인터페이스 (개념)
class ScoreModel(Protocol):
    def score(self, image: bytes) -> ScoreResult: ...

class CaptionModel(Protocol):
    def caption(self, image: bytes) -> CaptionResult: ...

class EmbeddingModel(Protocol):
    def embed(self, image: bytes) -> EmbeddingResult: ...

class AdvancedReviewModel(Protocol):
    def review(self, image: bytes, prompt: str) -> ReviewResult: ...
```

- local 구현: ONNX Runtime, llama.cpp
- remote 구현: REST 클라이언트(Anthropic SDK / OpenAI SDK / Google AI SDK)
- 설정으로 교체 가능

### 2.6 Storage
- 메타데이터: SQLite
- 임베딩: sqlite-vec 확장(또는 별도 Chroma collection)
- 썸네일: 로컬 파일 캐시(LRU, 기본 5GB)
- 백업: NAS 폴더 (DB 덤프 + 임베딩 + 썸네일)

### 2.7 Web UI (React + Vite)
- 페이지: Dashboard / Library / Search / Portfolio / Advanced / Settings / Logs
- API 클라이언트: fetch + 세션 쿠키
- 갤러리: react-photo-album

## 3. 디렉터리 구조

```
PhotoArchiveEvaluator/
├── docs/                          # 명세 문서 (위키 동기화 대상)
│   ├── SPEC.md
│   ├── MVP.md
│   ├── ARCHITECTURE.md
│   ├── SCHEMA.md
│   ├── Home.md
│   ├── _Sidebar.md
│   └── README.md
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI entry
│   │   ├── config.py              # 설정 로딩
│   │   ├── api/                   # 라우터(library, search, advanced, settings, ...)
│   │   ├── auth/                  # 비밀번호·세션
│   │   ├── nas/                   # FileStation 클라이언트
│   │   ├── scanner/               # 탐색 워커
│   │   ├── evaluator/             # 평가 파이프라인
│   │   ├── ai/                    # 어댑터
│   │   │   ├── base.py            # 인터페이스
│   │   │   ├── local/             # Aesthetic V2.5 / CLIP / BLIP-2 / ...
│   │   │   └── remote/            # Anthropic / OpenAI / Google
│   │   ├── storage/               # DB / 임베딩 / 썸네일
│   │   ├── scheduler/
│   │   ├── backup/
│   │   ├── search/                # 키워드 + 시맨틱
│   │   ├── settings/
│   │   └── observability/         # 로깅, 메트릭
│   ├── alembic/                   # 마이그레이션
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   └── api/
│   ├── package.json
│   └── vite.config.ts
├── scripts/
│   └── sync-wiki.sh               # 위키 수동 동기화
├── .github/
│   └── workflows/
│       └── sync-wiki.yml          # 위키 자동 동기화
├── LICENSE
├── README.md
└── .gitignore
```

## 4. 프로세스 모델

```
[OS service]
   ├── FastAPI (uvicorn)        ── 웹 UI / API
   ├── Scheduler                ── 일정 트리거
   ├── ScannerWorker            ── NAS walk → 후보 큐
   └── EvaluatorWorker × N      ── 큐 → 모델 호출 → DB
```

1차에는 **단일 프로세스 + asyncio**(단순성). 
GPU 호출이 CPU-bound 블로킹이 되는 경우 ProcessPoolExecutor로 격리.

## 5. 데이터 흐름 — 신규 사진

```
NAS → Scanner: 폴더 walk → 파일 후보
Scanner → DB:  (size, mtime) 캐시 조회. 일치하면 skip.
Scanner → Queue: 신규/변경 후보 enq
EvaluatorWorker ← Queue: deq (rate limit 적용)
EvaluatorWorker → NAS: JPG 다운로드 (스트리밍)
EvaluatorWorker → AI 어댑터: score / caption / embedding
EvaluatorWorker → DB: 결과 저장 + 상태 'done'
EvaluatorWorker → 썸네일 캐시: 생성
```

## 6. 데이터 흐름 — 고급 평가

```
UI → API: photo_id 다수 + model 선택
API → Cost Estimator: 추정 비용 계산
API ← UI: 사용자 확인 (비용 미리보기 다이얼로그)
API → AdvancedReviewModel: 호출
API → DB: advanced_reviews 행 추가, api_costs 기록
UI ← API: 결과 표시
```

## 7. 백업

```
스케줄러 → BackupJob:
  1. SQLite VACUUM INTO <임시>
  2. NAS 백업 폴더에 업로드
  3. 임베딩 폴더 / 썸네일 폴더 동기화 (변경분만)
  4. 보관 정책 적용 (세대 정리)
  5. backups 테이블에 이력 기록
```

복원: UI에서 백업 선택 → 현재 DB 잠금 → 백업 다운로드 → 검증 → 교체 → 재시작.

## 8. 회복성

- 시작 시 `in_progress` 상태 작업을 `pending`으로 되돌림
- 실패 카운터 N(기본 3) 초과 시 `failed`로 격리
- NAS 단절: 지수 백오프 재시도. 큐 일시정지
- 절전/슬립: 워커 일시정지 후 복귀 시 자동 재개
- 외부 API 단절: 해당 호출만 실패 처리, 다른 작업 계속

## 9. 보안

- 웹 UI: bcrypt 비밀번호 + 세션 쿠키 (HttpOnly, SameSite=Lax)
- 자격증명 보관:
  - Windows: DPAPI(`win32crypt`)
  - Linux: libsecret(secret-tool) 또는 fallback AES + 키파일(권한 0600)
- 외부 API 호출 전 동의 플래그 확인
- GPS / 민감 EXIF 제거 옵션 활성 시 임시 사본에서 제거 후 전송
- 인물 자동 감지(얼굴) 시 외부 전송 차단 옵션

## 10. 관측성

- 구조화 로그(JSON): `app.log`
- 메트릭: 처리량, 큐 길이, 평균 평가 시간, 비용
- 엔드포인트:
  - `GET /healthz` — 기본 헬스체크
  - `GET /metrics` — Prometheus 텍스트 포맷
  - `GET /api/status` — UI용 통합 상태(NAS, 큐, 모델, 디스크)
- 로그 다운로드(UI Logs 페이지)

## 11. 기술 스택 결정 요약

| 영역 | 선택 | 이유 |
|---|---|---|
| 백엔드 언어 | Python 3.11+ | ML 생태계, FastAPI, 어댑터 단순 |
| 웹 프레임워크 | FastAPI | 비동기, OpenAPI, 정적 서빙 |
| DB | SQLite + sqlite-vec | 단일 파일, 임베딩 동거, 운영 단순 |
| ORM / 마이그레이션 | SQLAlchemy + alembic | 표준, 타입 |
| 작업 스케줄 | APScheduler | 임베드, OS 독립 |
| 추론 백엔드 | ONNX Runtime + DirectML/CUDA | Windows/Linux 양립 |
| 프론트 | React + Vite + TypeScript | 갤러리 컴포넌트 풍부 |
| 패키징 | PyInstaller (Windows) + Docker (Linux) | 1차 사용자가 Windows |

## 12. 향후 검토 사항

- 처리량 부족 시 EvaluatorWorker를 별도 프로세스 풀로 분리
- 임베딩 규모가 수십만 건 넘어가면 sqlite-vec → Chroma/Qdrant 전환 검토
- NAS Docker(Container Manager)에 백엔드 일부 이전 가능성(GPU는 PC 유지)

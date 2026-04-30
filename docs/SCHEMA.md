# 데이터베이스 스키마

엔진: **SQLite** (Phase 1). 임베딩은 **sqlite-vec** 확장(또는 Chroma 별도 사용).
ORM: **SQLAlchemy 2.x**, 마이그레이션은 **alembic**.

> 본 문서는 논리 스키마이다. 실제 DDL은 alembic 마이그레이션이 단일 사실 출처이다.

---

## 1. 테이블 개요

| 테이블 | 역할 |
|---|---|
| `photos` | 발견된 사진(고유 식별 단위, SHA-256 기준) |
| `photo_paths` | 같은 사진의 NAS 경로(이동·이름변경 추적) |
| `evaluations` | 기본 평가 결과(점수 무관 모두 저장) |
| `embeddings` | 임베딩 벡터(모델별) |
| `tags` | 태그 사전 |
| `photo_tags` | 사진–태그 N:M |
| `categories` | 공모전 카테고리 사전 |
| `photo_categories` | 사진–카테고리 적합도 |
| `portfolios` | 포트폴리오 그룹 |
| `portfolio_items` | 그룹–사진 N:M (수동/AI 추천 구분) |
| `advanced_reviews` | 고급 평가 결과(다중 누적) |
| `user_scores` | 사용자 점수 오버라이드 |
| `scan_jobs` | 스캔 실행 단위 |
| `eval_jobs` | 평가 작업 단위(상태 트랜잭션) |
| `api_costs` | 외부 API 비용 추적 |
| `settings` | 키–값 설정 |
| `backups` | 백업 이력 |
| `audit_logs` | 운영 로그(중요 사건만) |

---

## 2. DDL (논리 스키마)

```sql
-- 2.1 photos: 고유 사진
CREATE TABLE photos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256        TEXT NOT NULL UNIQUE,
    phash         TEXT,                          -- 64-bit hex
    size_bytes    INTEGER NOT NULL,
    width         INTEGER,
    height        INTEGER,
    mime_type     TEXT NOT NULL,
    -- EXIF
    taken_at      DATETIME,
    camera_make   TEXT,
    camera_model  TEXT,
    lens_model    TEXT,
    iso           INTEGER,
    aperture      REAL,
    shutter       TEXT,
    focal_mm      REAL,
    gps_lat       REAL,
    gps_lon       REAL,
    -- 운영
    state         TEXT NOT NULL DEFAULT 'active', -- active | missing | deleted
    first_seen_at DATETIME NOT NULL,
    last_seen_at  DATETIME NOT NULL,
    updated_at    DATETIME NOT NULL
);
CREATE INDEX idx_photos_phash       ON photos(phash);
CREATE INDEX idx_photos_taken_at    ON photos(taken_at);
CREATE INDEX idx_photos_state       ON photos(state);

-- 2.2 photo_paths: NAS 경로(다중)
CREATE TABLE photo_paths (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id    INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    nas_id      TEXT NOT NULL,                  -- 다중 NAS 대비
    path        TEXT NOT NULL,                  -- 절대 경로
    size_bytes  INTEGER NOT NULL,
    mtime       DATETIME NOT NULL,
    last_seen_at DATETIME NOT NULL,
    UNIQUE(nas_id, path)
);
CREATE INDEX idx_photo_paths_photo ON photo_paths(photo_id);

-- 2.3 evaluations: 모든 기본 평가 결과 (이력 보존)
CREATE TABLE evaluations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id        INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    model_id        TEXT NOT NULL,             -- e.g. "aesthetic-v2.5"
    model_version   TEXT NOT NULL,
    ai_score        REAL,                      -- 1.0 - 5.0
    confidence      REAL,
    caption         TEXT,
    caption_lang    TEXT,
    composition     TEXT,                      -- JSON
    color_analysis  TEXT,                      -- JSON
    raw_response    TEXT,                      -- 디버깅용 원문 JSON
    created_at      DATETIME NOT NULL
);
CREATE INDEX idx_eval_photo_model ON evaluations(photo_id, model_id, created_at DESC);

-- 2.4 embeddings: 사진 임베딩
CREATE TABLE embeddings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id      INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    model_id      TEXT NOT NULL,                -- e.g. "clip-vit-l-14"
    model_version TEXT NOT NULL,
    dim           INTEGER NOT NULL,
    vector        BLOB NOT NULL,                -- float32 packed
    created_at    DATETIME NOT NULL,
    UNIQUE(photo_id, model_id, model_version)
);
-- sqlite-vec 가상 테이블(또는 외부 Chroma) 사용 시 별도 인덱스
-- CREATE VIRTUAL TABLE vec_embeddings USING vec0(embedding float[768]);

-- 2.5 tags
CREATE TABLE tags (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    source     TEXT NOT NULL                   -- 'ai' | 'user'
);

CREATE TABLE photo_tags (
    photo_id   INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    tag_id     INTEGER NOT NULL REFERENCES tags(id)   ON DELETE CASCADE,
    confidence REAL,                            -- AI 태그의 경우
    created_at DATETIME NOT NULL,
    PRIMARY KEY (photo_id, tag_id)
);

-- 2.6 categories (공모전)
CREATE TABLE categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,           -- 인물 / 풍경 / 스트리트 / 흑백 ...
    description TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE photo_categories (
    photo_id    INTEGER NOT NULL REFERENCES photos(id)     ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    score       REAL NOT NULL,                  -- 0.0 - 1.0 적합도
    model_id    TEXT NOT NULL,
    created_at  DATETIME NOT NULL,
    PRIMARY KEY (photo_id, category_id, model_id)
);

-- 2.7 portfolios
CREATE TABLE portfolios (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  DATETIME NOT NULL,
    updated_at  DATETIME NOT NULL
);

CREATE TABLE portfolio_items (
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    photo_id     INTEGER NOT NULL REFERENCES photos(id)     ON DELETE CASCADE,
    source       TEXT NOT NULL,                 -- 'manual' | 'ai_suggested'
    confirmed    INTEGER NOT NULL DEFAULT 0,    -- AI 추천 후 사용자 확정 여부
    rank         INTEGER,
    note         TEXT,
    added_at     DATETIME NOT NULL,
    PRIMARY KEY (portfolio_id, photo_id)
);

-- 2.8 advanced_reviews (다중 누적)
CREATE TABLE advanced_reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id    INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    model_id    TEXT NOT NULL,                  -- e.g. 'claude-opus-4-7'
    prompt      TEXT NOT NULL,
    response    TEXT NOT NULL,
    cost_usd    REAL,
    user_note   TEXT,
    user_tags   TEXT,                           -- JSON 배열
    created_at  DATETIME NOT NULL
);
CREATE INDEX idx_advrev_photo ON advanced_reviews(photo_id, created_at DESC);

-- 2.9 user_scores
CREATE TABLE user_scores (
    photo_id   INTEGER PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
    score      REAL NOT NULL,                   -- 1.0 - 5.0
    note       TEXT,
    updated_at DATETIME NOT NULL
);

-- 2.10 scan_jobs
CREATE TABLE scan_jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    DATETIME NOT NULL,
    finished_at   DATETIME,
    state         TEXT NOT NULL,                 -- pending | running | done | failed
    folders       TEXT NOT NULL,                 -- JSON 배열
    discovered    INTEGER NOT NULL DEFAULT 0,
    new_photos    INTEGER NOT NULL DEFAULT 0,
    changed       INTEGER NOT NULL DEFAULT 0,
    skipped       INTEGER NOT NULL DEFAULT 0,
    error         TEXT
);

-- 2.11 eval_jobs (재개 가능)
CREATE TABLE eval_jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id     INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,                 -- 'basic' | 'advanced'
    priority     INTEGER NOT NULL DEFAULT 0,    -- 신규 > 변경 > 재평가
    state        TEXT NOT NULL,                 -- pending | in_progress | done | failed
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT,
    enqueued_at  DATETIME NOT NULL,
    started_at   DATETIME,
    finished_at  DATETIME
);
CREATE INDEX idx_evaljobs_state_prio ON eval_jobs(state, priority DESC, enqueued_at);

-- 2.12 api_costs
CREATE TABLE api_costs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id    TEXT NOT NULL,
    photo_id    INTEGER REFERENCES photos(id) ON DELETE SET NULL,
    cost_usd    REAL NOT NULL,
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    created_at  DATETIME NOT NULL
);
CREATE INDEX idx_apicosts_created ON api_costs(created_at);

-- 2.13 settings
CREATE TABLE settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,                   -- JSON 또는 평문
    updated_at DATETIME NOT NULL
);

-- 2.14 backups
CREATE TABLE backups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  DATETIME NOT NULL,
    finished_at DATETIME,
    state       TEXT NOT NULL,
    nas_path    TEXT,                           -- 백업 위치
    size_bytes  INTEGER,
    photo_count INTEGER,
    error       TEXT
);

-- 2.15 audit_logs
CREATE TABLE audit_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    actor      TEXT NOT NULL,                   -- 'system' | 'user'
    event      TEXT NOT NULL,                   -- 'user_score_changed', 'backup_created', ...
    detail     TEXT,                            -- JSON
    created_at DATETIME NOT NULL
);
CREATE INDEX idx_audit_created ON audit_logs(created_at);
```

---

## 3. 인덱스 정책

- 검색 핫패스: `photos.taken_at`, `photos.phash`, `photo_tags(photo_id)`, `photo_tags(tag_id)`
- 큐 디큐 핫패스: `eval_jobs(state, priority, enqueued_at)`
- 시간 범위 조회: `api_costs.created_at`, `audit_logs.created_at`
- 시맨틱 검색: sqlite-vec ANN 인덱스(별도)

## 4. 제약·정책

- `photos.sha256` UNIQUE — 같은 콘텐츠는 1행
- `photo_paths(nas_id, path)` UNIQUE — 같은 경로 중복 방지
- `evaluations`: 동일 `(photo_id, model_id, model_version)`도 다중 행 허용(이력 보존). 활성 행은 `created_at` desc 최상단
- `embeddings`: `(photo_id, model_id, model_version)` UNIQUE — 모델 변경 시 재생성 필요
- `advanced_reviews`: 무제한 누적 (모델·시점 비교 가능)
- `user_scores`: photo 당 1행. 변경 시 `audit_logs`에 이전 값 기록
- `eval_jobs`: 시작 시 `in_progress` → `pending`으로 일괄 복구

## 5. 점수 / 표시 임계값

표시 점수는 다음 규칙으로 계산한다:

```sql
-- 의사 SQL
final_score = COALESCE(user_scores.score, latest(evaluations.ai_score))
is_visible  = final_score >= settings.value('display_threshold')
```

`display_threshold`는 `settings` 테이블에 저장(기본 `4.0`).
UI 필터링은 동적 쿼리에서 평가하며, 별도 머티리얼라이즈드 뷰는 1차에 두지 않는다.

## 6. 마이그레이션 정책

- 모든 변경은 alembic revision으로 관리
- 임베딩 모델 변경:
  1. 새 `model_id`/`model_version`으로 신규 행 추가
  2. UI에서 사용자에게 "재임베딩 필요" 배지 표시
  3. 백그라운드 점진적 재임베딩 잡 적재
  4. 검색은 새 모델 임베딩이 충분히 쌓이기 전까지 이전 모델 사용 가능
- 컬럼 삭제는 두 단계로(1) 신규 코드에서 미사용 처리 후 (2) 다음 릴리즈에서 alembic drop

## 7. 1차 예외 처리

- 손상 JPG / 0바이트 / EXIF 누락:
  - `photos`는 생성하되, `evaluations`에 실패 기록(`raw_response = error`, `ai_score = NULL`)
  - `eval_jobs.attempts` 증가, N회 초과 시 `failed`
- NAS 권한 거부: `photo_paths`에 마지막 본 시점 기록, 다음 회차 재시도

## 8. 향후 검토

- 임베딩 규모가 수십만 건을 넘으면 sqlite-vec → Chroma/Qdrant 전환
- 다중 NAS 정식 지원 시 `nas_id`를 별도 `nas_devices` 테이블로 정규화
- 다중 사용자 지원 시 `users`, `user_id` 외래키 추가

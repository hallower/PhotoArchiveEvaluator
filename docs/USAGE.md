# 사용 가이드 (Phase 1)

현재 시점에서 실행 가능한 모든 경로를 정리한다. 백엔드 + 프론트엔드가 한 프로세스에서 같이 돌고, 로컬 디스크 폴더의 JPG를 식별·평가·열람할 수 있다.

DSM (NAS) 클라이언트는 아직 미구현이라 NAS 사진은 SMB로 마운트한 폴더 경로를 로컬 스캔으로 입력해야 한다. 정식 DSM 어댑터는 다음 단계.

---

## 사전 준비 (1회)

### 1. 백엔드 의존성

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip install --upgrade --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu128
.\.venv\Scripts\python.exe -m pip install git+https://github.com/discus0434/aesthetic-predictor-v2-5.git
```

> Python 3.14 + RTX 40 시리즈 검증 조합. 다른 Python/GPU는 [backend/README.md](https://github.com/hallower/PhotoArchiveEvaluator/blob/main/backend/README.md) 참고.

### 2. DB 초기화

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade head
```

`backend/data/photo_archive.sqlite`이 생성된다. 이미 있으면 스킵.

### 3. 프론트엔드 빌드

```powershell
cd frontend
npm install
npm run build
```

`frontend/dist`가 생성되면 백엔드가 자동으로 마운트한다.

---

## 일상 사용

### A. 본 운영 모드 (단일 프로세스)

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8770
```

브라우저에서 http://127.0.0.1:8770 접속.
- 최초 1회: 비밀번호 8자 이상 설정
- 이후: 로그인 → 라이브러리 화면

### B. 프론트 개발 모드 (HMR)

백엔드는 위와 동일하게 실행하고, 별도 셸에서:

```powershell
cd frontend
npm run dev
```

http://127.0.0.1:5173 으로 접속하면 HMR로 즉시 반영. `/api/*`는 백엔드(8770)로 자동 프록시.

---

## 사진 등록·평가 절차

### CLI 경로

```powershell
cd backend
# 1) 폴더 스캔 — JPG 식별, photos/photo_paths upsert, 평가 큐에 enqueue
.\.venv\Scripts\python.exe -m scripts.scan_local "C:\path\to\photos"

# 2) 평가 큐 처리 — pending 잡들을 모델에 통과시켜 evaluations 행 생성
.\.venv\Scripts\python.exe -m scripts.process_eval_queue
```

### 웹 UI 경로

1. 헤더의 **스캔** 버튼 → 절대경로 입력 → 백그라운드 스캔 시작
2. 헤더의 **평가 처리** 버튼 → 워커 백그라운드 실행
3. 큐 통계 바가 5초마다 자동 갱신. 평가가 끝나면 **새로고침**으로 라이브러리에 반영

---

## 화면 사용

- **최소 점수 필터**: 기본 4점 이상. 4점 이상 = 공모전급, 5점 = 포트폴리오급(현재 정규화 기준, [POC_REPORT](POC_REPORT) 참조)
- **정렬**: 촬영일/점수/등록순
- **카드 클릭**: 800px 썸네일 + EXIF / 점수 / 경로 보기. ESC/배경클릭으로 닫기
- **로그아웃**: 세션 종료. 다시 들어오려면 로그인

---

## 데이터 / 로그 위치

| 경로 | 내용 |
|---|---|
| `backend/data/photo_archive.sqlite` | 메인 DB |
| `backend/data/thumbs/` | 썸네일 캐시 (LRU 미적용, 무제한 누적) |
| `backend/data/logs/app.log` | 백엔드 로그 |
| `backend/data/session.key` | 세션 서명 키 (재시작해도 세션 유지) |

전부 `.gitignore` 처리. 다른 PC로 옮길 땐 `data/` 폴더만 같이 복사.

---

## 흔한 문제

### `.venv\Scripts\Activate.ps1`가 실행 안 됨
PowerShell ExecutionPolicy 때문. 본 가이드는 venv 활성화 없이 `.venv\Scripts\python.exe`를 직접 호출하므로 문제 없음.

### 8770 포트 충돌
다른 포트로 띄울 때:
```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8771
```
프론트 dev 모드를 쓸 거면 `frontend/vite.config.ts`의 proxy target도 같이 바꿔야 한다.

### 비밀번호를 잊어버림
```powershell
cd backend
.\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('data/photo_archive.sqlite'); c.execute(\"DELETE FROM settings WHERE key='auth.password_hash'\"); c.commit()"
```
이후 다시 접속하면 setup 화면으로 돌아간다.

### 모델이 점수를 못 매김 / 4점 이상이 너무 적음
[POC_REPORT](POC_REPORT)에 캘리브레이션 결정과 정규화 공식 설명. 사용자 라이브러리 분포에 맞춰 조정 가능.

---

## 현재 미구현 (예정)

- DSM FileStation 클라이언트 (NAS 직접 접속) — 현재는 SMB 마운트 후 로컬 경로로 우회
- pHash (이름변경/리사이즈 추적)
- CLIP 임베딩 / 시맨틱 검색
- 공모전 카테고리 분류
- 고급 평가(외부 API)
- 자동 일정·백업

전체 로드맵은 [MVP](MVP)에서 단계별로 정리.

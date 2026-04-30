# backend/

Photo Archive Evaluator 백엔드 코드. 1차 산출물은 **Phase 1 PoC**(미학 모델
점수 분포 측정).

상위 명세는 [/docs/SPEC.md](../docs/SPEC.md) 참조.

## Phase 1 PoC — Aesthetic Predictor V2.5 점수 분포 확인

본격 구현 전 사용자 사진에 대한 미학 점수 분포를 파악하고, SPEC의 표시
임계값(기본 4.0)이 사용자 라이브러리에 적절한지 검증한다.

### 사전 요구

- Python 3.11+
- (권장) NVIDIA GPU + CUDA. 없으면 CPU(느림)
- 디스크 약 2GB (모델 가중치)

### 설치

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

GPU 사용 시 PyTorch는 CUDA 빌드를 따로 설치한다.

```powershell
# Python 3.14 + RTX 40 시리즈 검증된 조합 (PoC 사용)
pip install --upgrade --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

Python 3.13 이하라면 `cu124`도 사용 가능. 본인 환경에 맞춰 선택.

Aesthetic Predictor V2.5는 PyPI 패키지가 없으므로 별도 설치한다.

```powershell
pip install git+https://github.com/discus0434/aesthetic-predictor-v2-5.git
```

### 실행

```powershell
python -m scripts.poc_score_folder C:\path\to\photos --out poc_scores.csv
```

옵션:
- `--device cuda|cpu` (기본: 자동)
- `--limit N` 처리 최대 장 수
- `--out scores.csv` 출력 CSV 경로

### 출력
- `poc_scores.csv`: 사진별 점수 (정규화 1–5점, 모델 원본 1–10점)
- 콘솔: 1–5점 버킷 히스토그램, 표시 임계값(4점) 이상 비율

### 검증 기준
- 100~500장 표본으로 1회 실행
- 사용자가 30장 무작위 표본을 직접 1–5점 매기고 모델 점수와 비교
- 동의율 ±1점 이내가 70% 이상이면 SPEC 성공 기준 충족

이 결과에 따라:
- 임계값을 4.0이 아닌 다른 값으로 조정
- 모델 fine-tune 또는 교체 고려
- 사용자 점수 오버라이드 UI를 우선순위 높게 배치

## 디렉터리

```
backend/
├── app/                 # 라이브러리 코드 (재사용)
│   └── ai/
│       ├── base.py      # 어댑터 Protocol
│       └── local/
│           └── aesthetic.py
├── scripts/             # 일회성 / PoC / 운영 스크립트
│   └── poc_score_folder.py
└── pyproject.toml
```

## 보안 / 공개 저장소 주의

- API 키, NAS 자격증명, 사용자 사진 경로를 절대 커밋하지 않는다
- 로컬 설정은 `*.local.*`, `secrets/` 패턴으로 .gitignore 처리됨
- 테스트용 사진은 `photos/`, `sample_photos/`에 두면 자동 무시

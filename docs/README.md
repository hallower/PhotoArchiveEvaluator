# docs/

본 폴더는 Photo Archive Evaluator의 **명세 문서**가 위치한다.
GitHub Wiki에 자동 동기화되어 [GitHub Wiki](https://github.com/hallower/PhotoArchiveEvaluator/wiki)에서도 같은 내용을 볼 수 있다.

## 파일 구성

| 파일 | 위키 페이지 | 내용 |
|---|---|---|
| `SPEC.md` | SPEC | 전체 명세 |
| `MVP.md` | MVP | 단계별 범위 |
| `ARCHITECTURE.md` | ARCHITECTURE | 시스템 설계 |
| `SCHEMA.md` | SCHEMA | DB 스키마 |
| `Home.md` | Home | 위키 진입 페이지 |
| `_Sidebar.md` | (사이드바) | 위키 좌측 네비게이션 |

## 위키 동기화

### 자동 (권장)

main 브랜치에 `docs/` 변경이 push 되면 [`.github/workflows/sync-wiki.yml`](../.github/workflows/sync-wiki.yml)이
자동으로 위키 저장소에 반영한다.

> **최초 1회만 수동 작업이 필요하다.**
> GitHub 웹 UI에서 저장소 → **Wiki** 탭 → "Create the first page" 버튼으로
> 빈 페이지를 한 번 생성·저장해야 위키 저장소가 초기화된다. 이후부터는 자동.

### 수동

위키만 빠르게 갱신하고 싶을 때:

```bash
bash scripts/sync-wiki.sh
```

## 변경 절차

1. `docs/` 안의 문서를 PR로 수정
2. 리뷰·머지
3. main 머지 → 위키 자동 반영

## 작성 규칙

- 한국어 기본. 코드/식별자는 영문
- 위키 내 링크는 `[Title](Filename-Without-Extension)` 형식
- 변경이 큰 경우 SPEC의 단일 사실 출처 원칙 유지: 다른 문서가 SPEC을 참조하도록
- 결정의 **이유**를 명시. 단순 사실 나열 지양

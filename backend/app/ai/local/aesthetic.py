"""Aesthetic Predictor V2.5 (SigLIP 기반) 로컬 어댑터.

upstream: https://github.com/discus0434/aesthetic-predictor-v2-5

모델 raw 출력은 명목상 1–10 스케일이지만, 실제 사진 라이브러리에서는
대부분 4–7 범위에 강하게 분포한다(PoC 측정, 113장 후지 X 시리즈).
0–100점 스케일에 매핑하기 위해 `(raw - 2) * 100/6`으로 변환한 뒤
[0, 100]으로 클램프한다 — raw 2를 0점, raw 8을 100점으로 두면
실제 분포(4.3–7.0)가 ~38–83 범위에 펼쳐져 100점에 몰리지 않는다.

대응 의미:
  raw 2 → 0점   (very poor)
  raw 3 → 17점  (poor)
  raw 4 → 33점  (mediocre)
  raw 5 → 50점  (decent, library-worthy)
  raw 6 → 67점  (strong, contest-candidate)
  raw 7 → 83점  (excellent, portfolio-worthy)
  raw 8 → 100점 (outstanding, rare)

raw_score는 항상 보존하므로 추후 사용자 라이브러리에 맞춘 재캘리브레이션이
가능하다(percentile 기반 등).
"""

from __future__ import annotations

import io

import torch
from PIL import Image, ImageOps

from ..base import ScoreResult

MODEL_ID = "aesthetic-predictor-v2.5"
MODEL_VERSION = "siglip-so400m-patch14-384"

# 정규화 파라미터: raw 2 → 0점, raw 8 → 100점 (선형). 기존 데이터 재계산에서도
# 같은 함수를 사용하도록 별도 함수로 분리.
_NORM_MIN_RAW = 2.0
_NORM_MAX_RAW = 8.0


def normalize_raw(raw: float) -> float:
    """Aesthetic V2.5 raw 점수를 0–100으로 변환. 기존 데이터 재계산용으로도 사용."""
    span = _NORM_MAX_RAW - _NORM_MIN_RAW
    return max(0.0, min(100.0, (raw - _NORM_MIN_RAW) * 100.0 / span))


class AestheticV25:
    model_id: str = MODEL_ID
    model_version: str = MODEL_VERSION

    def __init__(
        self,
        device: str | None = None,
        dtype: torch.dtype | None = None,
    ) -> None:
        # 지연 import: 패키지 미설치 시에도 모듈 로딩만으로는 실패하지 않게 한다.
        from aesthetic_predictor_v2_5 import convert_v2_5_from_siglip

        self.device: str = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.dtype: torch.dtype = dtype or (
            torch.bfloat16 if self.device == "cuda" else torch.float32
        )

        model, preprocessor = convert_v2_5_from_siglip(
            low_cpu_mem_usage=True,
            trust_remote_code=True,
        )
        self._model = model.to(self.dtype).to(self.device).eval()
        self._preprocessor = preprocessor

    def score(self, image: bytes) -> ScoreResult:
        with Image.open(io.BytesIO(image)) as img:
            # EXIF Orientation을 적용해 회전된 사진을 똑바로 평가한다.
            img = ImageOps.exif_transpose(img).convert("RGB")
            pixel_values = self._preprocessor(images=img, return_tensors="pt").pixel_values

        pixel_values = pixel_values.to(self.dtype).to(self.device)

        with torch.inference_mode():
            raw = self._model(pixel_values).logits.squeeze().float().cpu().item()

        return ScoreResult(
            score=normalize_raw(raw),
            raw_score=raw,
            confidence=1.0,
            model_id=self.model_id,
            model_version=self.model_version,
        )

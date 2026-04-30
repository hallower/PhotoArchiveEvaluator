"""Aesthetic Predictor V2.5 (SigLIP 기반) 로컬 어댑터.

upstream: https://github.com/discus0434/aesthetic-predictor-v2-5

모델 raw 출력은 명목상 1–10 스케일이지만, 실제 사진 라이브러리에서는
대부분 3–8 범위에 분포한다(PoC 측정). SPEC의 1–5점에 매핑하기 위해
`raw - 2`로 시프트한 뒤 [1, 5]로 클램프한다.

대응 의미:
  raw  3 → 1점 (poor)
  raw  4 → 2점 (mediocre)
  raw  5 → 3점 (decent)
  raw  6 → 4점 (strong, contest-worthy)
  raw  7 → 5점 (excellent, portfolio-worthy)

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

        normalized = max(1.0, min(5.0, raw - 2.0))

        return ScoreResult(
            score=normalized,
            raw_score=raw,
            confidence=1.0,
            model_id=self.model_id,
            model_version=self.model_version,
        )

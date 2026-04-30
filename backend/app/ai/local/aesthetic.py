"""Aesthetic Predictor V2.5 (SigLIP 기반) 로컬 어댑터.

upstream: https://github.com/discus0434/aesthetic-predictor-v2-5

모델은 약 1.0 - 10.0 스케일로 점수를 출력한다. 우리는 SPEC에 맞춰 1.0 - 5.0으로
정규화하되, 원본 점수도 함께 보존한다(추후 임계값 캘리브레이션용).
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
        from aesthetics_predictor import convert_v2_5_from_siglip

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

        normalized = max(1.0, min(5.0, raw / 2.0))

        return ScoreResult(
            score=normalized,
            raw_score=raw,
            confidence=1.0,
            model_id=self.model_id,
            model_version=self.model_version,
        )

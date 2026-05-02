"""BLIP base 캡션 어댑터.

Salesforce/blip-image-captioning-base — transformers 네이티브 지원.
ViT 인코더 + 트랜스포머 디코더, ~250M params, fp16에서 ~500MB VRAM.
RTX 4050 6GB에서 AestheticV25 + CLIP과 동시 적재 가능.

Florence-2는 transformers 5.x에서 forced_bos_token_id 호환성 문제로 사용 못함.
"""

from __future__ import annotations

import io
import logging

import torch
from PIL import Image, ImageOps

from ..base import CaptionResult

log = logging.getLogger(__name__)

MODEL_NAME = "Salesforce/blip-image-captioning-base"
MODEL_ID = "blip"
MODEL_VERSION = "base"


class BlipCaption:
    model_id: str = MODEL_ID
    model_version: str = MODEL_VERSION

    def __init__(self, device: str | None = None, dtype: torch.dtype | None = None) -> None:
        from transformers import BlipForConditionalGeneration, BlipProcessor

        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.dtype = dtype or (torch.float16 if self.device == "cuda" else torch.float32)

        self._processor = BlipProcessor.from_pretrained(MODEL_NAME)
        self._model = (
            BlipForConditionalGeneration.from_pretrained(MODEL_NAME)
            .to(self.dtype)
            .to(self.device)
            .eval()
        )

    def caption(self, image: bytes) -> CaptionResult:
        with Image.open(io.BytesIO(image)) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            inputs = self._processor(images=img, return_tensors="pt")

        pixel_values = inputs["pixel_values"].to(self.dtype).to(self.device)

        with torch.inference_mode():
            generated_ids = self._model.generate(
                pixel_values=pixel_values,
                max_length=50,
                num_beams=3,
                early_stopping=True,
            )

        text = self._processor.decode(generated_ids[0], skip_special_tokens=True).strip()

        return CaptionResult(
            caption=text,
            lang="en",
            model_id=self.model_id,
            model_version=self.model_version,
        )

"""HuggingFace CLIP 어댑터.

이미지/텍스트를 768d 정규화 벡터로 사상한다(ViT-L/14). RTX 4050 6GB에서
AestheticV25와 동시 적재 가능 (대략 합산 ~3GB VRAM 상수).

prompt → 1-5 정규화 공식은 evaluator/worker.py의 _prompt_score 참조.
"""

from __future__ import annotations

import io

import numpy as np
import torch
from PIL import Image, ImageOps

from ..embed import EmbeddingResult

MODEL_NAME = "openai/clip-vit-large-patch14"
MODEL_ID = "clip"
MODEL_VERSION = "vit-l-14"
DIM = 768


class CLIPLocal:
    model_id: str = MODEL_ID
    model_version: str = MODEL_VERSION
    dim: int = DIM

    def __init__(self, device: str | None = None, dtype: torch.dtype | None = None) -> None:
        from transformers import CLIPModel, CLIPProcessor

        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.dtype = dtype or (
            torch.float16 if self.device == "cuda" else torch.float32
        )

        self._model = (
            CLIPModel.from_pretrained(MODEL_NAME).to(self.dtype).to(self.device).eval()
        )
        self._processor = CLIPProcessor.from_pretrained(MODEL_NAME)

    def embed_image(self, image: bytes) -> EmbeddingResult:
        with Image.open(io.BytesIO(image)) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            inputs = self._processor(images=img, return_tensors="pt")
        pixel_values = inputs["pixel_values"].to(self.dtype).to(self.device)

        with torch.inference_mode():
            # transformers 5.x: get_*_features는 BaseModelOutputWithPooling을 반환하며,
            # 투영(projection)이 적용된 임베딩은 pooler_output에 들어 있다.
            out = self._model.get_image_features(pixel_values=pixel_values)
            features = out.pooler_output
            features = features / features.norm(dim=-1, keepdim=True)

        return self._to_result(features)

    def embed_text(self, text: str) -> EmbeddingResult:
        inputs = self._processor(
            text=[text], return_tensors="pt", padding=True, truncation=True
        )
        input_ids = inputs["input_ids"].to(self.device)
        attention_mask = inputs["attention_mask"].to(self.device)

        with torch.inference_mode():
            out = self._model.get_text_features(
                input_ids=input_ids, attention_mask=attention_mask
            )
            features = out.pooler_output
            features = features / features.norm(dim=-1, keepdim=True)

        return self._to_result(features)

    def _to_result(self, features) -> EmbeddingResult:
        vec = features.squeeze().float().cpu().numpy().astype(np.float32)
        return EmbeddingResult(
            vector=vec.tobytes(),
            dim=int(vec.shape[0]),
            model_id=self.model_id,
            model_version=self.model_version,
        )

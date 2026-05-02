"""EXIF·GPS 메타데이터 제거.

외부 API 전송 전 임시 사본을 만들어 EXIF/GPS 정보를 모두 떼어낸다 (SPEC §5.5).
PIL로 디코드 후 새 이미지로 재인코딩 — 모든 메타데이터 자동 제거.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps


def strip_exif_jpeg(data: bytes, quality: int = 92) -> bytes:
    """JPEG bytes에서 EXIF/GPS 등 모든 메타데이터를 제거하고 재인코딩.

    EXIF Orientation은 적용 후 폐기 (사진이 똑바로 보이게 픽셀 회전 후 메타 제거).
    """
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        out = io.BytesIO()
        # save without exif=... 인자 → PIL이 메타데이터 미포함으로 출력
        img.save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue()

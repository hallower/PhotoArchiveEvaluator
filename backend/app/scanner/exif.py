"""JPEG EXIF 파싱.

Pillow의 getexif() + get_ifd()를 사용해 SCHEMA의 EXIF 컬럼들을 추출한다.
누락된 필드는 None으로 둔다 — Phase 1에서는 best-effort.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import ExifTags, Image, UnidentifiedImageError

log = logging.getLogger(__name__)

_EXIF_IFD_TAG = 0x8769
_GPS_IFD_TAG = 0x8825


@dataclass
class ImageMeta:
    width: int | None = None
    height: int | None = None
    taken_at: datetime | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    lens_model: str | None = None
    iso: int | None = None
    aperture: float | None = None
    shutter: str | None = None
    focal_mm: float | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None


def parse(path: Path) -> ImageMeta:
    meta = ImageMeta()
    try:
        with Image.open(path) as img:
            meta.width, meta.height = img.size
            exif = img.getexif()
            if not exif:
                return meta
            base = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
            ifd = {ExifTags.TAGS.get(k, k): v for k, v in exif.get_ifd(_EXIF_IFD_TAG).items()}

            meta.camera_make = _clean_str(base.get("Make"))
            meta.camera_model = _clean_str(base.get("Model"))
            meta.lens_model = _clean_str(ifd.get("LensModel"))
            meta.taken_at = _parse_datetime(ifd.get("DateTimeOriginal") or base.get("DateTime"))
            meta.iso = _coerce_int(ifd.get("ISOSpeedRatings"))
            meta.aperture = _coerce_float(ifd.get("FNumber"))
            meta.shutter = _format_shutter(ifd.get("ExposureTime"))
            meta.focal_mm = _coerce_float(ifd.get("FocalLength"))

            gps_ifd = exif.get_ifd(_GPS_IFD_TAG)
            if gps_ifd:
                meta.gps_lat = _gps_to_decimal(gps_ifd.get(2), gps_ifd.get(1))
                meta.gps_lon = _gps_to_decimal(gps_ifd.get(4), gps_ifd.get(3))
    except (UnidentifiedImageError, OSError) as exc:
        log.warning("EXIF read failed %s: %s", path, exc)
    return meta


def _clean_str(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            return None
    s = str(value).strip().strip("\x00")
    return s or None


def _parse_datetime(value) -> datetime | None:
    s = _clean_str(value)
    if not s:
        return None
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _coerce_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (tuple, list)):
        if not value:
            return None
        value = value[0]
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_shutter(value) -> str | None:
    f = _coerce_float(value)
    if f is None or f <= 0:
        return None
    if f >= 1:
        return f"{f:.2f}"
    try:
        return f"1/{int(round(1 / f))}"
    except (ValueError, ZeroDivisionError):
        return None


def _gps_to_decimal(value, ref) -> float | None:
    if value is None:
        return None
    try:
        d, m, s = value
        deg = float(d) + float(m) / 60 + float(s) / 3600
    except (TypeError, ValueError):
        return None
    if ref in ("S", "W", b"S", b"W"):
        deg = -deg
    return deg

"""환경 변수 / .env 기반 설정.

우선순위: 환경변수 (PAE_*) > .env > 기본값.
런타임 변경되는 사용자 설정은 settings 테이블에 저장하며 본 모듈은 부팅 단계만 담당.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PAE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 서버
    host: str = "127.0.0.1"
    port: int = 8765
    log_level: str = "INFO"

    # 데이터 위치
    data_dir: Path = Path("./data")
    db_url: str = "sqlite:///./data/photo_archive.sqlite"

    @property
    def thumb_dir(self) -> Path:
        return self.data_dir / "thumbs"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"


settings = Settings()

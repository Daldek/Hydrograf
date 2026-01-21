"""
Application configuration module.

Loads settings from environment variables with sensible defaults.
"""

import os
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Attributes
    ----------
    database_url : str
        PostgreSQL connection string
    log_level : str
        Logging level (DEBUG, INFO, WARNING, ERROR)
    cors_origins : str
        Comma-separated list of allowed CORS origins
    imgw_grid_spacing_km : float
        Grid spacing for IMGW data preprocessing [km]
    imgw_rate_limit_delay_s : float
        Delay between IMGW API requests [s]
    """

    # Database - can be set via DATABASE_URL or individual components
    database_url_override: Optional[str] = None
    postgres_db: str = "hydro_db"
    postgres_user: str = "hydro_user"
    postgres_password: str = "hydro_password"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # API
    log_level: str = "INFO"
    cors_origins: str = (
        "http://localhost,http://localhost:8080,http://127.0.0.1,http://127.0.0.1:8080"
    )

    # IMGW preprocessing
    imgw_grid_spacing_km: float = 2.0
    imgw_rate_limit_delay_s: float = 0.5

    @property
    def database_url(self) -> str:
        """Build PostgreSQL connection URL."""
        # Check for DATABASE_URL environment variable first (used in Docker)
        env_url = os.getenv("DATABASE_URL")
        if env_url:
            return env_url
        if self.database_url_override:
            return self.database_url_override
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Returns
    -------
    Settings
        Application settings
    """
    return Settings()

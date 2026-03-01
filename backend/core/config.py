"""
Application configuration module.

Loads settings from environment variables with sensible defaults.
Supports YAML configuration file for pipeline customization.
"""

import os
from copy import deepcopy
from functools import lru_cache

import yaml
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
    database_url_override: str | None = None
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

    # Database safety
    db_statement_timeout_ms: int = 120000  # 120s

    # DEM raster path (for terrain profile sampling)
    dem_path: str = "/data/dem/dem.vrt"

    # Admin panel API key (empty = auth disabled)
    admin_api_key: str = ""

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


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Returns
    -------
    Settings
        Application settings
    """
    return Settings()


# ---------------------------------------------------------------------------
# YAML pipeline configuration
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG = {
    "database": {
        "host": "localhost",
        "port": 5432,
        "name": "hydro_db",
        "user": "hydro_user",
        "password": "hydro_password",
    },
    "dem": {
        "resolution": "5m",
        "thresholds_m2": [1000, 10000, 100000],
        "burn_depth_m": 10.0,
        "building_raise_m": 5.0,
    },
    "paths": {
        "output_dir": "output",
        "frontend_data": "frontend/data",
        "dem_tiles_dir": "frontend/data/dem_tiles",
    },
    "steps": {
        "download_nmt": True,
        "process_dem": True,
        "landcover": True,
        "soil_hsg": True,
        "precipitation": True,
        "depressions": True,
        "tiles": True,
        "overlays": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*, returning a new dict."""
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_config(path: str) -> dict:
    """Load pipeline config from a YAML file, merging with defaults.

    If the file does not exist, returns default configuration.
    Partial YAML files are merged — missing keys fall back to defaults.
    """
    config = deepcopy(_DEFAULT_CONFIG)
    if os.path.exists(path):
        with open(path) as f:
            user_config = yaml.safe_load(f) or {}
        config = _deep_merge(config, user_config)
    return config


def get_database_url_from_config(config: dict) -> str:
    """Build a PostgreSQL connection URL from YAML config dict."""
    db = config["database"]
    return (
        f"postgresql://{db['user']}:{db['password']}"
        f"@{db['host']}:{db['port']}/{db['name']}"
    )

"""
Application configuration module.

Loads settings from environment variables with sensible defaults.
Supports YAML configuration file for pipeline customization.
"""

import logging
import os
from copy import deepcopy
from functools import lru_cache

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


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
    postgres_password: str = ""
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # API
    log_level: str = "INFO"
    cors_origins: str = (
        "http://localhost,http://localhost:8080,http://127.0.0.1,http://127.0.0.1:8080"
    )

    # Database safety
    db_statement_timeout_ms: int = 120000  # 120s

    # DEM raster directory (contains pipeline outputs)
    dem_dir: str = "/data/nmt"

    # DEM raster path (for terrain profile sampling) — overridable via DEM_PATH env
    dem_path: str = ""

    # Stream distance raster path (for flow path point sampling)
    stream_distance_path: str = ""

    def resolve_dem_path(self) -> str | None:
        """Find the best available DEM raster, checking candidates in order.

        Priority: DEM_PATH env override → VRT mosaic → raw DEM TIF → filled DEM.
        Returns None if no DEM found.
        """
        if self.dem_path and os.path.exists(self.dem_path):
            return self.dem_path
        candidates = [
            os.path.join(self.dem_dir, "dem_mosaic.vrt"),
            os.path.join(self.dem_dir, "dem_mosaic_01_dem.tif"),
            os.path.join(self.dem_dir, "dem_mosaic.tif"),
            os.path.join(self.dem_dir, "dem_mosaic_02_filled.tif"),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

    def resolve_stream_distance_path(self) -> str | None:
        """Find stream distance raster."""
        if self.stream_distance_path and os.path.exists(self.stream_distance_path):
            return self.stream_distance_path
        candidate = os.path.join(self.dem_dir, "dem_mosaic_04b_stream_distance.tif")
        return candidate if os.path.exists(candidate) else None

    def resolve_flowdir_path(self) -> str | None:
        """Find flow direction raster (pyflwdir uint8 D8)."""
        candidate = os.path.join(self.dem_dir, "dem_mosaic_03_flowdir.tif")
        return candidate if os.path.exists(candidate) else None

    def resolve_slope_path(self) -> str | None:
        """Find slope raster."""
        candidate = os.path.join(self.dem_dir, "dem_mosaic_05_slope.tif")
        return candidate if os.path.exists(candidate) else None

    # Admin panel API key (empty = auto-generated UUID at startup)
    admin_api_key: str = ""
    admin_api_key_file: str = ""  # Path to file containing admin API key

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

    def warn_if_default_credentials(self) -> None:
        """Log warning if database credentials are not configured."""
        if not self.postgres_password:
            logger.warning(
                "POSTGRES_PASSWORD is empty. "
                "Set POSTGRES_PASSWORD env var for production."
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
    settings = Settings()
    settings.warn_if_default_credentials()
    return settings


# ---------------------------------------------------------------------------
# YAML pipeline configuration
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG = {
    "database": {
        "host": "localhost",
        "port": 5432,
        "name": "hydro_db",
        "user": "hydro_user",
        "password": "",
    },
    "dem": {
        "resolution": "5m",
        "thresholds_m2": [1000, 10000, 100000],
        "burn_depth_m": 2.0,
        "building_raise_m": 5.0,
    },
    "paths": {
        "output_dir": "output",
        "cache_dir": "cache",
        "frontend_data": "frontend/data",
        "dem_tiles_dir": "frontend/data/dem_tiles",
    },
    "steps": {
        "download_nmt": True,
        "process_dem": True,
        "landcover": True,
        "soil_hsg": True,
        "precipitation": True,
        "depressions": False,
        "tiles": True,
        "overlays": True,
    },
    "sewer": {
        "enabled": False,
        "inlet_burn_depth_m": 0.5,
        "snap_tolerance_m": 2.0,
        "source": {
            "type": "file",
            "path": None,
            "url": None,
            "layer": None,
            "connection": None,
            "table": None,
            "lines_layer": None,
            "points_layer": None,
            "assumed_crs": None,
        },
        "attribute_mapping": {
            "diameter": None,
            "width": None,
            "height": None,
            "cross_section": None,
            "invert_start": None,
            "invert_end": None,
            "depth": None,
            "material": None,
            "manning": None,
            "flow_direction": None,
            "node_type": None,
            "rim_elevation": None,
            "max_depth": None,
            "ponded_area": None,
            "outfall_type": None,
        },
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

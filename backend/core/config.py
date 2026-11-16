"""
Application configuration module.

Loads settings from environment variables with sensible defaults.
Supports YAML configuration file for pipeline customization.
"""

import json
import logging
import os
import re
import tomllib
from copy import deepcopy
from functools import cache, lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import platformdirs
import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.active_run import active_run_raster
from utils.kartograf_store import DEFAULT_HSG_DEPTH_RULE

logger = logging.getLogger(__name__)

# A registry name of the ecosystem in lower case, a key of the table `gui` (DEV-15.4)
_GUI_NAME = re.compile(r"[a-z][a-z0-9-]*")


def _is_gui_address(address: str) -> bool:
    """Whether an address is an http or https URL or a path from / on this host."""
    if address.startswith("/"):
        return not address.startswith("//")
    parts = urlsplit(address)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def gui_table(text: str) -> dict[str, str]:
    """Return the GUIs of the deployment from the value of HYDROGRAF_GUI (ADR-082).

    The value is the table ``gui`` of ``[nogat]`` in ``nogat.toml`` (DEV-15.4,
    DEV-18.1) as a JSON object, e.g. ``{"hydrolog": "http://127.0.0.1:8070/"}``: a
    registry name in lower case to the address of that GUI, an http or https URL or
    a path from ``/`` on this host. An empty value is an empty table, so the app menu
    of the top bar is not drawn.

    Raises
    ------
    ValueError
        When the value is not such an object.
    """
    if not text.strip():
        return {}
    try:
        table = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"HYDROGRAF_GUI is not JSON: {error}") from error
    return _checked_gui(table, "HYDROGRAF_GUI")


def _checked_gui(table: object, source: str) -> dict[str, str]:
    """Return a table ``gui`` (DEV-15.4) read from ``source``, checked.

    Raises
    ------
    ValueError
        When it is not an object of registry names and http, https or ``/`` addresses.
    """
    if not isinstance(table, dict):
        raise ValueError(f"{source} must map GUI names to their addresses")
    gui: dict[str, str] = {}
    for name, address in table.items():
        if not _GUI_NAME.fullmatch(name):
            raise ValueError(f"{source}: {name!r} is not a registry name in lower case")
        if not isinstance(address, str) or not _is_gui_address(address):
            raise ValueError(
                f"{source}: the address of {name!r} must be an http or https URL "
                "or a path from /"
            )
        gui[name] = address
    return gui


@cache
def nogat_table(path: str, section: str = "nogat") -> dict[str, Any]:
    """Return a section of the ``nogat.toml`` at ``path`` (DEV-18.1).

    Hydrograf reads two tables of ``[nogat]``: ``operator``, who runs a deployment
    open to others (the regulamin, DEV-15.7, ADR-084), and ``gui`` when HYDROGRAF_GUI
    is not set; and ``state_dir`` of ``[hydrograf]`` and ``[nogat]`` (``state_dir()``).
    An empty path, an empty file (the Docker default mounts ``/dev/null``), a missing
    section or a file that cannot be read or parsed give an empty table; the last two,
    and a section that is not a table, are logged. The file is read once per process
    and section: a change needs a restart of the API.
    """
    if not path:
        return {}
    try:
        with open(path, "rb") as file:
            document = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        logger.warning("nogat.toml at NOGAT_CONFIG=%s cannot be read: %s", path, error)
        return {}
    table = document.get(section, {})
    if not isinstance(table, dict):
        logger.warning(
            "nogat.toml at NOGAT_CONFIG=%s: [%s] is not a table", path, section
        )
        return {}
    return table


def deployment_gui(settings: "Settings") -> dict[str, str]:
    """Return the GUIs of the deployment (DEV-15.4, DEV-18.1; ADR-082, ADR-084).

    HYDROGRAF_GUI when it is set, else the table ``gui`` of ``[nogat]`` in the
    ``nogat.toml`` of NOGAT_CONFIG, else an empty table. A table of the file that the
    menu cannot use is logged and ignored.
    """
    if settings.hydrograf_gui.strip():
        return gui_table(settings.hydrograf_gui)
    table = nogat_table(settings.nogat_config).get("gui")
    if table is None:
        return {}
    try:
        return _checked_gui(table, "[nogat] gui of nogat.toml")
    except ValueError as error:
        logger.warning("%s", error)
        return {}


def state_dir(settings: "Settings") -> Path:
    """Return the deployment's ``state_dir`` (DEV-18.1, DEV-18.2).

    The first of HYDROGRAF_STATE_DIR, NOGAT_STATE_DIR, ``state_dir`` of
    ``[hydrograf]`` and of ``[nogat]`` in the ``nogat.toml`` of NOGAT_CONFIG, and
    ``platformdirs.user_state_path("nogat")`` (``~/.local/state/nogat`` on Linux).
    The server's logs are ``<state_dir>/hydrograf/logs`` (DEV-12.6); in Docker
    NOGAT_STATE_DIR is ``/state``, where the host's ``<state_dir>/hydrograf`` is
    mounted. A value of the file that is not a text is logged and skipped.
    """
    for variable in (settings.hydrograf_state_dir, settings.nogat_state_dir):
        if variable.strip():
            return Path(variable).expanduser()
    for section in ("hydrograf", "nogat"):
        value = nogat_table(settings.nogat_config, section).get("state_dir")
        if isinstance(value, str) and value.strip():
            return Path(value).expanduser()
        if value is not None and not isinstance(value, str):
            logger.warning("[%s] state_dir of nogat.toml is not a path", section)
    return platformdirs.user_state_path("nogat")


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

    # Frontend data served by nginx under /data/ (mounted in the API container);
    # holds the analysis results manifest results/index.json
    frontend_data_dir: str = "/frontend/data"

    # The GUIs of the deployment that the app menu of the top bar lists (ADR-082): the
    # table `gui` of `[nogat]` in nogat.toml (DEV-15.4, DEV-18.1) as a JSON object,
    # read by gui_table(); empty, the table of NOGAT_CONFIG's file (deployment_gui())
    hydrograf_gui: str = ""

    # The nogat.toml of the deployment (DEV-18.1): its `[nogat]` tables `operator`, for
    # the regulamin (DEV-15.7, ADR-084), and `gui`; empty, none is read
    nogat_config: str = ""

    # Requests per client address and window (DEV-15.9, ADR-084): pages and API routes;
    # map tiles have ten times the limit in the same window
    hydrograf_request_limit: int = Field(300, ge=1)
    hydrograf_request_window: int = Field(60, ge=1)  # seconds

    # The deployment's data_dir (DEV-18.2): the daily statistics are
    # <data_dir>/hydrograf/stats.jsonl (DEV-15.11)
    hydrograf_data_dir: str = "/data"

    # The deployment's state_dir (DEV-18.1, DEV-18.2), resolved by state_dir(): the
    # server's logs are <state_dir>/hydrograf/logs (DEV-12.6)
    hydrograf_state_dir: str = ""
    nogat_state_dir: str = ""

    @field_validator("hydrograf_gui")
    @classmethod
    def _check_gui(cls, value: str) -> str:
        """Refuse a table the menu cannot use when the settings load."""
        gui_table(value)
        return value

    def resolve_dem_path(self) -> str | None:
        """Find the best available DEM raster, checking candidates in order.

        Priority: DEM_PATH env override → the active unit run's VRT mosaic
        (``core.active_run``) → input VRT mosaic → raw DEM TIF → filled DEM.
        Returns None if no DEM found.
        """
        if self.dem_path and os.path.exists(self.dem_path):
            return self.dem_path
        active = self._active_run_raster("01_dem")
        if active is not None:
            return active
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
        """Find stream distance raster.

        Priority: STREAM_DISTANCE_PATH env override → the active unit run's VRT
        mosaic → the GeoTIFF of a run of the whole raster.
        """
        if self.stream_distance_path and os.path.exists(self.stream_distance_path):
            return self.stream_distance_path
        return self.resolve_pipeline_raster("04b_stream_distance")

    def resolve_flowdir_path(self) -> str | None:
        """Find flow direction raster (pyflwdir uint8 D8)."""
        return self.resolve_pipeline_raster("03_flowdir")

    def resolve_subcatchment_labels_path(self, threshold_m2: int) -> str | None:
        """Find the sub-catchment label raster of a threshold (int32, segment_idx)."""
        return self.resolve_pipeline_raster(f"10_subcatchments_{threshold_m2}")

    def resolve_slope_path(self) -> str | None:
        """Find slope raster."""
        return self.resolve_pipeline_raster("05_slope")

    def _active_run_raster(self, raster: str) -> str | None:
        """``dem_mosaic_<raster>.vrt`` of the active unit run of DEM_DIR, or None."""
        mosaic = active_run_raster(self.dem_dir, raster)
        return str(mosaic) if mosaic is not None else None

    def resolve_pipeline_raster(self, raster: str) -> str | None:
        """Return a raster of the pipeline in DEM_DIR, or None if it has none.

        The VRT mosaic of the active unit run (``core.active_run``) when DEM_DIR
        holds a valid pointer and the run has that raster; else the GeoTIFF
        ``dem_mosaic_<raster>.tif`` of a run of the whole raster.
        """
        active = self._active_run_raster(raster)
        if active is not None:
            return active
        candidate = os.path.join(self.dem_dir, f"dem_mosaic_{raster}.tif")
        return candidate if os.path.exists(candidate) else None

    # The admin key (Nogat DEV-15.13, ADR-086): ADMIN_API_KEY, else the text of the file
    # ADMIN_API_KEY_FILE names, read on every request; with neither, every admin route
    # refuses (401, admin_key_not_configured). Never logged.
    admin_api_key: str = ""
    admin_api_key_file: str = ""

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

# The keys that the pipeline reads (scripts/bootstrap.py, scripts/process_dem.py,
# scripts/download_sewer.py and the sewer routes of the admin API)
_DEFAULT_CONFIG = {
    "dem": {
        # BDOT10k streams burned into the DEM: "all" or "main" (core.hydrology)
        "stream_burning": "all",
        # Interpolate the nodata the DEM data encloses before the fill, so that it
        # drains nothing (core.hydrology.interpolate_enclosed_nodata)
        "fill_enclosed_nodata": False,
    },
    "soil": {
        # The SoilGrids layers of the soil groups of bootstrap step 5 (ADR-079):
        # "least-permeable" (the least permeable layer of 0-100 cm) or "topsoil" (the
        # 0-5 cm layer); utils.kartograf_store.HSG_DEPTH_RULES
        "hsg_depth_rule": DEFAULT_HSG_DEPTH_RULE,
    },
    "paths": {
        "cache_dir": "cache",
    },
    "sewer": {
        "enabled": False,
        "inlet_burn_depth_m": 0.5,
        "source": {
            "type": "file",
            "path": None,
            "lines_layer": None,
            "points_layer": None,
            "assumed_crs": None,
            "format": "auto",
        },
        "field_mapping": {
            "node_id": "id",
            "node_role": "role",
            "downstream_id": "downstream_id",
            "edge_from": "from_node",
            "edge_to": "to_node",
            "invert_elev": None,
            "depth": None,
            "diameter": None,
            "rim_elevation": None,
            "max_depth": None,
            "ponded_area": None,
            "outfall_type": None,
            "manning": None,
            "material": None,
            "cross_section": None,
            "width": None,
            "height": None,
        },
        "role_mapping": {
            "inlet": "inlet",
            "outlet": "outlet",
            "junction": "junction",
            "storage": "storage",
        },
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict."""
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_config(path: str) -> dict[str, Any]:
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

"""
Server-side DuckDB service for H3 crop production & drought risk queries.

Downloads an H3 GeoParquet file from Azure Blob Storage on startup,
creates an in-memory DuckDB view over the local cache, and serves
queries via asyncio.to_thread() to avoid blocking the event loop.

Feature-flagged via ENABLE_H3_DUCKDB. Non-fatal on init failure —
the rest of the app (TiTiler, TiPG, STAC) continues normally.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import duckdb
import requests

from geotiler.config import settings
from geotiler.auth.cache import storage_token_cache

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


# =============================================================================
# STARTUP STATE TRACKING (follows TiPGStartupState pattern)
# =============================================================================

class DuckDBStartupState:
    """Captures DuckDB initialization state for health endpoint."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.init_success: bool = False
        self.init_error: Optional[str] = None
        self.last_init_time: Optional[datetime] = None
        self.row_count: int = 0
        self.columns: list[str] = []
        self.parquet_path: Optional[str] = None
        self.download_time_ms: Optional[float] = None

    def record_success(
        self,
        parquet_path: str,
        row_count: int,
        columns: list[str],
        download_time_ms: float,
    ):
        self.last_init_time = datetime.now(timezone.utc)
        self.init_success = True
        self.init_error = None
        self.parquet_path = parquet_path
        self.row_count = row_count
        self.columns = columns[:100]  # Cap for diagnostics
        self.download_time_ms = round(download_time_ms, 1)

    def record_failure(self, error: str):
        self.last_init_time = datetime.now(timezone.utc)
        self.init_success = False
        self.init_error = error

    def to_dict(self) -> dict:
        return {
            "init_success": self.init_success,
            "init_error": self.init_error,
            "last_init_time": self.last_init_time.isoformat() if self.last_init_time else None,
            "row_count": self.row_count,
            "columns": self.columns,
            "parquet_path": self.parquet_path,
            "download_time_ms": self.download_time_ms,
        }


# =============================================================================
# INPUT VALIDATION (frozen sets prevent SQL injection)
# =============================================================================

VALID_CROPS = frozenset([
    "bana", "barl", "bean", "cass", "chic", "citr", "cnut", "coco", "coff",
    "cott", "cowp", "grou", "lent", "maiz", "mill", "ocer", "ofib", "oilp",
    "onio", "ooil", "opul", "orts", "pige", "plnt", "pmil", "pota", "rape",
    "rcof", "rest", "rice", "rubb", "sesa", "sorg", "soyb", "sugb", "sugc",
    "sunf", "swpo", "teas", "temf", "toba", "toma", "trof", "vege", "whea",
    "yams",
])

VALID_TECHS = frozenset(["a", "i", "r"])

VALID_SCENARIOS = frozenset([
    # 2050 climate projections
    "spei12_ssp370_median", "spei12_ssp370_p10",
    "spei12_ssp585_median", "spei12_ssp585_p10",
    # ERA5 observed (annual mean / annual min)
    "spei12_era5_2022_mean", "spei12_era5_2022_min",
    "spei12_era5_2023_mean", "spei12_era5_2023_min",
    "spei12_era5_2024_mean", "spei12_era5_2024_min",
])


def validate_h3_params(crop: str, tech: str, scenario: str) -> None:
    """Validate query parameters against allowed values. Raises ValueError."""
    errors = []
    if crop not in VALID_CROPS:
        errors.append(f"Invalid crop: {crop!r}")
    if tech not in VALID_TECHS:
        errors.append(f"Invalid tech: {tech!r}")
    if scenario not in VALID_SCENARIOS:
        errors.append(f"Invalid scenario: {scenario!r}")
    if errors:
        raise ValueError("; ".join(errors))


# =============================================================================
# PARQUET DOWNLOAD
# =============================================================================

def _download_parquet(url: str, dest_path: str) -> float:
    """
    Download parquet file from Azure Blob Storage.

    Uses the server's cached storage OAuth token for authentication.
    Skips download if file already exists locally.

    Returns download time in milliseconds (0 if skipped).
    """
    if os.path.exists(dest_path):
        size_mb = os.path.getsize(dest_path) / (1024 * 1024)
        logger.info(f"Parquet cache exists: {dest_path} ({size_mb:.1f} MB) — skipping download")
        return 0.0

    # Ensure directory exists
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    logger.info(f"Downloading parquet from {url}")
    t0 = time.monotonic()

    headers = {
        # Azure Blob Storage REST API requires x-ms-version for OAuth bearer auth
        "x-ms-version": "2020-04-08",
    }
    token = storage_token_cache.get_if_valid(min_ttl_seconds=60)
    if token:
        headers["Authorization"] = f"Bearer {token}"
        logger.info("Using storage OAuth token for parquet download")
    else:
        logger.warning("No storage token available — attempting anonymous download")

    resp = requests.get(url, headers=headers, stream=True, timeout=300)
    resp.raise_for_status()

    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8 * 1024 * 1024):
            f.write(chunk)

    elapsed_ms = (time.monotonic() - t0) * 1000
    size_mb = os.path.getsize(dest_path) / (1024 * 1024)
    logger.info(f"Parquet downloaded: {size_mb:.1f} MB in {elapsed_ms:.0f}ms")
    return elapsed_ms


# =============================================================================
# DUCKDB CONNECTION
# =============================================================================

def _create_duckdb_connection(parquet_path: str) -> tuple[duckdb.DuckDBPyConnection, int, list[str]]:
    """
    Create in-memory DuckDB connection with a view over the local parquet.

    Returns (connection, row_count, column_names).
    """
    conn = duckdb.connect(":memory:")
    conn.execute(
        f"CREATE VIEW h3_data AS SELECT * FROM read_parquet('{parquet_path}')"
    )

    row_count = conn.execute("SELECT count(*) FROM h3_data").fetchone()[0]
    columns = [
        col[0] for col in conn.execute("DESCRIBE h3_data").fetchall()
    ]

    logger.info(f"DuckDB view created: {row_count:,} rows, {len(columns)} columns")
    return conn, row_count, columns


# =============================================================================
# LIFECYCLE (called from app.py lifespan)
# =============================================================================

async def initialize_duckdb(app: "FastAPI") -> None:
    """
    Download parquet and create DuckDB connection.

    Stores on app.state:
    - duckdb_conn: DuckDB connection
    - duckdb_state: DuckDBStartupState
    - duckdb_columns: list of column names (for validation)

    Non-fatal — logs error and continues if init fails.
    """
    state = DuckDBStartupState()
    app.state.duckdb_state = state
    app.state.duckdb_conn = None
    app.state.duckdb_columns = []

    parquet_path = os.path.join(settings.h3_data_dir, settings.h3_parquet_filename)

    try:
        logger.info("Initializing H3 DuckDB service...")

        # Download parquet (runs in thread pool — blocking I/O)
        download_ms = await asyncio.to_thread(
            _download_parquet, settings.h3_parquet_url, parquet_path
        )

        # Create DuckDB connection (runs in thread pool — DuckDB is sync)
        conn, row_count, columns = await asyncio.to_thread(
            _create_duckdb_connection, parquet_path
        )

        app.state.duckdb_conn = conn
        app.state.duckdb_columns = columns
        app.state.duckdb_query_cache = {}
        state.record_success(parquet_path, row_count, columns, download_ms)

        logger.info(
            f"H3 DuckDB ready: {row_count:,} rows, {len(columns)} columns"
        )

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.error(f"H3 DuckDB initialization failed: {error_msg}")
        logger.warning("H3 server-side queries will not be available")
        state.record_failure(error_msg)


async def close_duckdb(app: "FastAPI") -> None:
    """Close DuckDB connection on shutdown."""
    conn = getattr(app.state, "duckdb_conn", None)
    if conn:
        try:
            await asyncio.to_thread(conn.close)
            logger.info("DuckDB connection closed")
        except Exception as e:
            logger.warning(f"Error closing DuckDB: {e}")


# =============================================================================
# QUERY
# =============================================================================

def _run_query(conn: duckdb.DuckDBPyConnection, prod_col: str, harv_col: str, scenario: str) -> list[dict]:
    """Execute H3 query synchronously. Called via asyncio.to_thread()."""
    sql = f"""
        SELECT h3_index, "{prod_col}" as production, "{harv_col}" as harv_area_ha, "{scenario}" as spei
        FROM h3_data
        WHERE "{prod_col}" > 0 AND "{prod_col}" IS NOT NULL
    """
    rows = conn.execute(sql).fetchall()
    return [
        {"h3_index": r[0], "production": r[1], "harv_area_ha": r[2] or 0, "spei": r[3]}
        for r in rows
    ]


_QUERY_CACHE_MAX = 100


async def query_h3_data(
    app: "FastAPI", crop: str, tech: str, scenario: str
) -> tuple[list[dict], bool]:
    """
    Validate parameters and query H3 data.

    Returns (data, from_cache). Raises ValueError for invalid params,
    RuntimeError if DuckDB not ready.
    """
    validate_h3_params(crop, tech, scenario)

    conn = getattr(app.state, "duckdb_conn", None)
    if not conn:
        raise RuntimeError("DuckDB not initialized")

    # Check server-side cache
    cache_key = (crop, tech, scenario)
    query_cache = getattr(app.state, "duckdb_query_cache", None)
    if query_cache is not None and cache_key in query_cache:
        return query_cache[cache_key], True

    prod_col = f"{crop}_{tech}_production_mt"
    harv_col = f"{crop}_{tech}_harv_area_ha"

    # Verify columns exist in parquet schema
    columns = getattr(app.state, "duckdb_columns", [])
    if prod_col not in columns:
        raise ValueError(f"Column not found in dataset: {prod_col}")
    if harv_col not in columns:
        raise ValueError(f"Column not found in dataset: {harv_col}")
    if scenario not in columns:
        raise ValueError(f"Scenario column not found: {scenario}")

    result = await asyncio.to_thread(_run_query, conn, prod_col, harv_col, scenario)

    # Store in cache (LRU eviction at max size)
    if query_cache is not None:
        if len(query_cache) >= _QUERY_CACHE_MAX:
            query_cache.pop(next(iter(query_cache)))
        query_cache[cache_key] = result

    return result, False

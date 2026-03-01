"""
Spatial query service for PostGIS vector data.

Queries PostGIS tables via asyncpg, returning features as async iterators
for streaming serialization. Uses TiPG's collection catalog for table
discovery and validation.

Spec: Component 5 — Vector Query Service
Handles: R3 (asyncpg pool starvation — statement_timeout + connection acquisition timeout)
"""

import asyncio
import json
import logging
import re
from typing import AsyncIterator, Optional, TYPE_CHECKING

import asyncpg

if TYPE_CHECKING:
    from geotiler.services.download import ParsedBbox

logger = logging.getLogger(__name__)

# SQL identifier validation: letters, digits, underscores only
_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Connection acquisition timeout in seconds
_CONN_ACQUIRE_TIMEOUT_SEC = 5.0


def _validate_identifier(name: str, label: str) -> None:
    """
    Validate a SQL identifier against injection attacks.

    Args:
        name: The identifier to validate.
        label: Human-readable label for error messages.

    Raises:
        ValueError: If the identifier contains unsafe characters.

    Spec: Component 5 — SQL identifier validation
    Handles: Critic concern — SQL injection prevention
    """
    if not _IDENTIFIER_PATTERN.match(name):
        raise ValueError(
            f"Invalid {label}: '{name}' — must match [a-zA-Z_][a-zA-Z0-9_]*"
        )


class VectorQueryService:
    """
    Spatial query service for PostGIS tables discovered by TiPG.

    Uses asyncpg pool from app.state.pool and TiPG's collection_catalog
    for table validation. Supports bbox intersection queries with
    configurable limits and timeouts.

    Spec: Component 5 — VectorQueryService class
    Handles: R3 (pool starvation), R6 (stale TiPG catalog)
    """

    def __init__(self, pool: asyncpg.Pool, catalog: dict, settings):
        """
        Initialize with asyncpg pool and TiPG catalog.

        Args:
            pool: asyncpg connection pool (from app.state.pool).
            catalog: TiPG collection catalog (from app.state.collection_catalog).
            settings: geotiler Settings instance.

        Spec: Component 5 — VectorQueryService.__init__
        """
        self._pool = pool
        self._catalog = catalog  # None means catalog not initialized
        self._max_features = settings.download_vector_max_features
        self._query_timeout_sec = settings.download_vector_query_timeout_sec

    @property
    def catalog_available(self) -> bool:
        """True if the TiPG catalog has been initialized."""
        return self._catalog is not None

    def collection_exists(self, collection_id: str) -> bool:
        """
        Check if a collection exists in the TiPG catalog.

        Spec: Component 5 — collection_exists
        Handles: R6 (stale TiPG catalog — 404 is actionable)

        Raises:
            RuntimeError: If catalog is None (not initialized).
        """
        if self._catalog is None:
            raise RuntimeError("TiPG catalog not initialized")
        return collection_id in self._catalog

    def get_collection_table_info(self, collection_id: str) -> tuple[str, str, str]:
        """
        Get schema, table name, and geometry column for a collection.

        Args:
            collection_id: TiPG collection identifier (matches PostGIS table).

        Returns:
            Tuple of (schema, table, geometry_column).

        Raises:
            ValueError: If collection not found or table info unavailable.

        Spec: Component 5 — get_collection_table_info
        """
        if collection_id not in self._catalog:
            raise ValueError(f"Collection not found: {collection_id}")

        collection = self._catalog[collection_id]

        # TiPG catalog entries have schema, table, and geometry column info
        # The exact attribute names depend on TiPG version — handle common patterns
        schema = getattr(collection, "schema", None) or getattr(collection, "dbschema", None)
        if not schema:
            raise ValueError(
                f"Cannot determine schema for collection '{collection_id}'. "
                f"TiPG catalog entry has no 'schema' or 'dbschema' attribute."
            )
        table = getattr(collection, "table", None) or getattr(collection, "id", collection_id)
        geom_col = self._get_geometry_column(collection)

        # Validate identifiers to prevent SQL injection
        _validate_identifier(schema, "schema")
        _validate_identifier(table, "table")
        _validate_identifier(geom_col, "geometry column")

        return schema, table, geom_col

    async def count_features(
        self,
        collection_id: str,
        bbox: Optional["ParsedBbox"] = None,
    ) -> int:
        """
        Count features matching the spatial filter.

        Args:
            collection_id: TiPG collection identifier.
            bbox: Optional bounding box filter.

        Returns:
            Number of matching features.

        Spec: Component 5 — count_features
        """
        schema, table, geom_col = self.get_collection_table_info(collection_id)

        if bbox:
            sql = (
                f'SELECT COUNT(*) FROM "{schema}"."{table}" '
                f'WHERE ST_Intersects("{geom_col}", ST_MakeEnvelope($1, $2, $3, $4, 4326))'
            )
            params = [bbox.minx, bbox.miny, bbox.maxx, bbox.maxy]
        else:
            sql = f'SELECT COUNT(*) FROM "{schema}"."{table}"'
            params = []

        try:
            async with asyncio.timeout(_CONN_ACQUIRE_TIMEOUT_SEC):
                conn = await self._pool.acquire()
        except asyncio.TimeoutError:
            raise asyncpg.InterfaceError("Connection pool exhausted — could not acquire connection")

        try:
            await conn.execute(
                f"SET statement_timeout = '{int(self._query_timeout_sec * 1000)}'"
            )
            row = await conn.fetchrow(sql, *params)
            return row[0] if row else 0
        except asyncpg.QueryCanceledError:
            raise
        finally:
            try:
                await conn.execute("RESET statement_timeout")
            except Exception:
                pass
            await self._pool.release(conn)

    async def query_features(
        self,
        collection_id: str,
        bbox: Optional["ParsedBbox"] = None,
        limit: Optional[int] = None,
        include_centroid: bool = False,
    ) -> AsyncIterator[dict]:
        """
        Query features from a PostGIS table with optional spatial filter.

        Returns an async iterator of feature dicts, each containing:
        - All table columns (excluding raw geometry)
        - '__geojson': parsed GeoJSON geometry dict
        - 'latitude'/'longitude': centroid coords (when include_centroid=True)

        Args:
            collection_id: TiPG collection identifier.
            bbox: Optional bounding box filter.
            limit: Maximum features to return (capped by download_vector_max_features).
            include_centroid: Add latitude/longitude centroid columns (for CSV export).

        Yields:
            Feature dicts ready for serialization.

        Raises:
            asyncpg.InterfaceError: Pool exhausted (maps to 503).
            asyncpg.QueryCanceledError: statement_timeout exceeded (maps to 504).
            asyncpg.UndefinedTableError: Table not found (maps to 404).

        Spec: Component 5 — query_features
        Handles: R3 (pool starvation — semaphore + timeout + conn acquisition timeout)
        """
        schema, table, geom_col = self.get_collection_table_info(collection_id)

        # Apply limit (capped at max_features)
        effective_limit = min(limit, self._max_features) if limit else self._max_features

        # Build SELECT clause
        select_parts = [
            "*",
            f'ST_AsGeoJSON("{geom_col}")::json AS __geojson',
        ]
        if include_centroid:
            select_parts.append(f'ST_Y(ST_Centroid("{geom_col}")) AS latitude')
            select_parts.append(f'ST_X(ST_Centroid("{geom_col}")) AS longitude')

        select_clause = ", ".join(select_parts)

        # Build WHERE clause
        if bbox:
            where_clause = (
                f'WHERE ST_Intersects("{geom_col}", ST_MakeEnvelope($1, $2, $3, $4, 4326))'
            )
            params = [bbox.minx, bbox.miny, bbox.maxx, bbox.maxy, effective_limit]
            limit_param = "$5"
        else:
            where_clause = ""
            params = [effective_limit]
            limit_param = "$1"

        sql = (
            f'SELECT {select_clause} FROM "{schema}"."{table}" '
            f'{where_clause} LIMIT {limit_param}'
        )

        logger.debug(
            f"Vector query: collection={collection_id} bbox={'yes' if bbox else 'no'} "
            f"limit={effective_limit}",
            extra={"event": "vector_query_start", "collection": collection_id},
        )

        # Acquire connection with timeout
        try:
            async with asyncio.timeout(_CONN_ACQUIRE_TIMEOUT_SEC):
                conn = await self._pool.acquire()
        except asyncio.TimeoutError:
            raise asyncpg.InterfaceError(
                "Connection pool exhausted — could not acquire connection"
            )

        try:
            # Set statement_timeout for this connection
            await conn.execute(
                f"SET statement_timeout = '{int(self._query_timeout_sec * 1000)}'"
            )

            # Stream results via cursor, excluding raw WKB geometry column
            stmt = await conn.prepare(sql)
            async for record in stmt.cursor(*params):
                row = dict(record)
                row.pop(geom_col, None)
                yield row

        except asyncpg.UndefinedTableError:
            logger.error(
                f"Table not found for collection {collection_id}: {schema}.{table}",
                extra={"event": "vector_query_table_not_found"},
            )
            raise
        except asyncpg.QueryCanceledError:
            logger.warning(
                f"Vector query timed out for {collection_id} "
                f"(timeout={self._query_timeout_sec}s)",
                extra={"event": "vector_query_timeout", "collection": collection_id},
            )
            raise
        except GeneratorExit:
            # Consumer abandoned iteration — connection will be released in finally
            logger.debug(
                f"Vector query generator closed early for {collection_id}",
                extra={"event": "vector_query_generator_closed", "collection": collection_id},
            )
            return
        finally:
            try:
                await conn.execute("RESET statement_timeout")
            except Exception:
                pass
            await self._pool.release(conn)
            logger.debug(
                f"Vector query connection released for {collection_id}",
                extra={"event": "vector_query_conn_released", "collection": collection_id},
            )

    @staticmethod
    def _get_geometry_column(collection) -> str:
        """
        Extract geometry column name from TiPG collection entry.

        TiPG stores geometry info in different attributes depending on version.
        This method handles the common patterns.

        Spec: Component 5 — geometry column discovery from catalog
        """
        # Try common TiPG attribute patterns
        if hasattr(collection, "geometry_columns") and collection.geometry_columns:
            # TiPG >= 0.6: geometry_columns is a dict {col_name: GeometryColumn}
            if isinstance(collection.geometry_columns, dict):
                return next(iter(collection.geometry_columns.keys()))

        if hasattr(collection, "geometry_column") and collection.geometry_column:
            return collection.geometry_column

        # No silent fallback — raise so caller gets a clear error
        raise ValueError(
            "Cannot determine geometry column from TiPG catalog entry. "
            "Expected 'geometry_columns' or 'geometry_column' attribute."
        )

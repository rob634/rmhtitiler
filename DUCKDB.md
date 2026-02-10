# H3 Explorer — Server-Side DuckDB Backend

## Why Server-Side

The H3 Crop Production & Drought Risk Explorer originally ran DuckDB-WASM in the browser, querying parquet files directly from Azure Blob Storage via HTTP range requests. This worked but had three problems:

1. **Token leakage** — Server-side OAuth tokens had to be passed to the browser for DuckDB-WASM to authenticate against Azure Blob Storage.
2. **CORS configuration** — Every storage account needed CORS rules allowing the web app origin, with `Authorization` in allowed headers.
3. **Performance** — Each query downloaded 3-5 MB over the network. Server-side queries against a local parquet cache run in <100ms.

Moving the query engine server-side eliminates all three issues. Auth stays on the server (same pattern as COG/TiPG/STAC), no CORS needed, and queries are faster.

## Architecture

```
Browser (deck.gl + h3-js)
  │
  │  GET /h3/query?crop=whea&tech=a&scenario=spei12_ssp585_median
  │
  ▼
FastAPI router (geotiler/routers/h3_explorer.py)
  │
  │  asyncio.to_thread()  ← DuckDB Python API is synchronous
  │
  ▼
DuckDB (in-process, :memory: database)
  │
  │  CREATE VIEW h3_data AS SELECT * FROM read_parquet('/app/data/h3_data.parquet')
  │
  ▼
Local parquet file (downloaded from Azure Blob on startup)
```

DuckDB runs alongside TiTiler, TiPG, and STAC API in the same FastAPI process. It is feature-flagged via `ENABLE_H3_DUCKDB` — when disabled, the app starts normally without any DuckDB overhead.

## Data Flow

### Startup

1. App checks `ENABLE_H3_DUCKDB=true` and `H3_PARQUET_URL` is set
2. Downloads parquet from Azure Blob Storage to local cache (`/app/data/h3_data.parquet`)
   - Uses the server's existing storage OAuth token (same token GDAL uses for COG tiles)
   - Skips download if file already exists locally (fast restarts)
3. Creates an in-memory DuckDB connection with a VIEW over the local file
4. Stores connection and metadata on `app.state` (same pattern as TiPG pool)

### Query

1. Browser sends `GET /h3/query?crop=whea&tech=a&scenario=spei12_ssp585_median`
2. Router validates parameters against frozen sets (no raw user input in SQL)
3. Query runs via `asyncio.to_thread()` to avoid blocking the event loop
4. Returns JSON: `{"data": [...], "count": N, "query_ms": X}`
5. Browser renders hexagons with deck.gl PolygonLayer + h3-js (unchanged)

### Shutdown

1. DuckDB connection is closed in the app lifespan shutdown phase

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `ENABLE_H3_DUCKDB` | `false` | Enable server-side DuckDB query engine |
| `H3_PARQUET_URL` | (empty) | Azure Blob URL to the H3 GeoParquet file |
| `H3_DATA_DIR` | `/app/data` | Local directory for cached parquet file |
| `H3_PARQUET_FILENAME` | `h3_data.parquet` | Filename for the local cache |

## Query API

### `GET /h3/query`

Returns H3 hexagon data for a given crop, technology level, and climate scenario.

**Parameters:**

| Param | Required | Example | Description |
|-------|----------|---------|-------------|
| `crop` | yes | `whea` | 4-letter crop code (46 valid codes) |
| `tech` | yes | `a` | Technology: `a` (all), `i` (irrigated), `r` (rainfed) |
| `scenario` | yes | `spei12_ssp585_median` | SPEI-12 scenario column name (6 valid values) |

**Response:**
```json
{
    "data": [
        {"h3_index": "851f1a3fffffff", "production": 1234.5, "spei": -0.82},
        ...
    ],
    "count": 12847,
    "query_ms": 42.3
}
```

**Error responses:**
- `400` — Invalid crop, tech, or scenario parameter
- `503` — DuckDB not initialized

## Health Monitoring

The `/health` endpoint reports `h3_duckdb` as a service:

```json
{
    "services": {
        "h3_duckdb": {
            "status": "healthy",
            "available": true,
            "description": "H3 server-side DuckDB query engine",
            "endpoints": ["/h3/query"],
            "details": {
                "init_success": true,
                "last_init_time": "2025-01-15T10:30:00Z",
                "row_count": 230000,
                "columns": ["h3_index", "whea_a_production_mt", "..."],
                "parquet_path": "/app/data/h3_data.parquet",
                "download_time_ms": 3200.5
            }
        }
    }
}
```

Status values: `healthy` (working), `unavailable` (init failed), `disabled` (feature flag off).

DuckDB is **not** included in `/readyz` — it is optional and feature-flagged. Its failure does not affect COG, TiPG, STAC, or pgSTAC services.

## Input Validation

All query parameters are validated against frozen sets before constructing SQL:

- **Crops**: 46 valid 4-letter codes (`whea`, `maiz`, `rice`, etc.)
- **Technologies**: 3 valid codes (`a`, `i`, `r`)
- **Scenarios**: 6 valid SPEI column names

Column names are additionally verified against the actual parquet schema at startup. No raw user input ever appears in SQL strings.

## Concurrency Model

- **DuckDB Python API is synchronous** — all queries run via `asyncio.to_thread()` in the default thread pool
- **DuckDB supports concurrent reads** from a single connection — multiple `/h3/query` requests can run simultaneously
- **Single uvicorn worker** + thread pool handles this correctly (same as the existing deployment)
- The connection is stored on `app.state.duckdb_conn` (no module-level globals)

## Key Files

| File | Purpose |
|------|---------|
| `geotiler/services/duckdb.py` | Core service: download, connection, query, validation |
| `geotiler/routers/h3_explorer.py` | `/h3/query` endpoint and page template serving |
| `geotiler/config.py` | Settings: `enable_h3_duckdb`, `h3_data_dir`, `h3_parquet_filename` |
| `geotiler/app.py` | Lifespan integration (startup/shutdown) |
| `geotiler/routers/health.py` | Health check reporting |
| `geotiler/templates/pages/h3/explorer.html` | Browser-side rendering (deck.gl + h3-js) |

## Relationship to Other Services

DuckDB follows the same patterns as TiPG and STAC API:

| Aspect | TiPG | DuckDB |
|--------|------|--------|
| Startup state | `TiPGStartupState` | `DuckDBStartupState` |
| App state | `app.state.pool` | `app.state.duckdb_conn` |
| Init function | `initialize_tipg(app)` | `initialize_duckdb(app)` |
| Cleanup | `close_tipg(app)` | `close_duckdb(app)` |
| Feature flag | `ENABLE_TIPG` | `ENABLE_H3_DUCKDB` |
| Non-fatal init | Yes | Yes |
| Health reporting | In `/health` services | In `/health` services |

## Parquet Refresh

The parquet file is downloaded once on startup. To update the data, restart the container. The data changes infrequently (updated by ETL pipeline), so a refresh endpoint is not justified yet.

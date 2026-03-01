"""
Vector feature serializers for download endpoints.

Converts async iterators of feature dicts into streaming bytes
for GeoJSON and CSV output formats.

Spec: Component 9 — Vector Serializers
"""

import csv
import io
import json
import logging
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)


async def serialize_geojson(
    features: AsyncIterator[dict],
    feature_count: Optional[int] = None,
) -> AsyncIterator[bytes]:
    """
    Stream a GeoJSON FeatureCollection from an async iterator of feature dicts.

    Outputs framing (header, comma-separated features, footer) so the response
    can begin streaming before all features are materialized.

    Args:
        features: Async iterator yielding feature dicts with '__geojson' key
                  for geometry and remaining keys for properties.
        feature_count: Optional total count for the 'numberMatched' property.

    Yields:
        bytes chunks of the GeoJSON FeatureCollection.

    Spec: Component 9 — serialize_geojson
    """
    # FeatureCollection header
    header = '{"type": "FeatureCollection"'
    if feature_count is not None:
        header += f', "numberMatched": {feature_count}'
    header += ', "features": [\n'
    yield header.encode("utf-8")

    first = True
    emitted = 0
    async for feature in features:
        try:
            geojson_feature = _feature_to_geojson(feature)
        except Exception as e:
            logger.warning(
                f"Skipping non-serializable feature: {type(e).__name__}: {e}",
                extra={"event": "serialize_skip", "error": str(e)},
            )
            continue

        if not first:
            yield b",\n"
        first = False

        yield json.dumps(geojson_feature, default=str).encode("utf-8")
        emitted += 1

    # FeatureCollection footer
    yield f'\n], "numberReturned": {emitted}}}'.encode("utf-8")


async def serialize_csv(
    features: AsyncIterator[dict],
    geometry_mode: str = "centroid",
) -> AsyncIterator[bytes]:
    """
    Stream CSV from an async iterator of feature dicts.

    The header row is derived from the first feature's keys. Geometry is
    represented as centroid latitude/longitude columns (computed by the
    query service, not here).

    Args:
        features: Async iterator yielding feature dicts. Expected keys include
                  'latitude' and 'longitude' for centroid geometry (added by
                  the vector query service when format=csv).
        geometry_mode: How geometry is represented. Currently only 'centroid'
                       is supported.

    Yields:
        bytes chunks of the CSV file.

    Spec: Component 9 — serialize_csv
    """
    header_written = False
    fieldnames = None
    emitted = 0

    # Keys to exclude from CSV output (raw geometry data)
    _EXCLUDE_KEYS = {"__geojson", "geom", "geometry"}

    async for feature in features:
        try:
            # Build property dict, excluding raw geometry
            row = {
                k: v for k, v in feature.items()
                if k not in _EXCLUDE_KEYS
            }

            if not header_written:
                fieldnames = list(row.keys())
                buf = io.StringIO()
                writer = csv.DictWriter(buf, fieldnames=fieldnames)
                writer.writeheader()
                yield buf.getvalue().encode("utf-8")
                header_written = True

            extra_keys = set(row.keys()) - set(fieldnames)
            if extra_keys:
                logger.warning(
                    f"CSV row has {len(extra_keys)} columns not in header: {sorted(extra_keys)[:5]}",
                    extra={"event": "serialize_csv_extra_columns", "extra_count": len(extra_keys)},
                )
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
            writer.writerow(row)
            yield buf.getvalue().encode("utf-8")
            emitted += 1

        except Exception as e:
            logger.warning(
                f"Skipping non-serializable CSV row: {type(e).__name__}: {e}",
                extra={"event": "serialize_csv_skip", "error": str(e)},
            )
            continue

    if not header_written:
        # No features — yield empty CSV with just a comment
        yield b"# No features found\n"

    logger.debug(f"CSV serialization complete: {emitted} rows")


def _feature_to_geojson(feature: dict) -> dict:
    """
    Convert a database row dict to a GeoJSON Feature.

    Expects '__geojson' key with parsed geometry JSON.
    All other keys become properties.

    Spec: Component 9 — internal GeoJSON feature conversion
    """
    geometry = feature.get("__geojson")
    if geometry is None:
        raise ValueError("Feature missing '__geojson' geometry key")

    # Build properties from all non-geometry keys
    _GEOM_KEYS = {"__geojson", "geom", "geometry"}
    properties = {k: v for k, v in feature.items() if k not in _GEOM_KEYS}

    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": properties,
    }

"""
Filename generation and sanitization for download endpoints.

Generates deterministic, human-readable filenames for raster crops,
vector subsets, and proxied asset downloads.

Spec: Component 8 — Filename Generator
"""

import re
from datetime import date, timezone, datetime
from typing import Optional


# Regex for allowed characters in filenames
_SAFE_CHARS = re.compile(r"[^a-zA-Z0-9._-]")

# Maximum filename length (excluding extension)
_MAX_FILENAME_LENGTH = 200


def generate_filename(
    *,
    prefix: str,
    source_name: str,
    bbox: Optional[str] = None,
    format_ext: str,
    generation_date: Optional[date] = None,
) -> str:
    """
    Generate a deterministic download filename.

    Pattern: {prefix}_{source_name}_{bbox_summary}_{date}.{ext}

    Spec: Component 8 — generate_filename
    """
    if generation_date is None:
        generation_date = datetime.now(timezone.utc).date()

    parts = [prefix, _clean_part(source_name)]

    if bbox:
        parts.append(_bbox_summary(bbox))

    parts.append(generation_date.strftime("%Y%m%d"))

    # Join and sanitize
    base = "_".join(parts)
    base = _SAFE_CHARS.sub("_", base)

    # Trim to max length
    if len(base) > _MAX_FILENAME_LENGTH:
        base = base[:_MAX_FILENAME_LENGTH]

    # Ensure extension starts without dot if already present
    ext = format_ext.lstrip(".")

    return f"{base}.{ext}"


def sanitize_filename(user_filename: str) -> str:
    """
    Sanitize a user-provided filename for safe use in Content-Disposition.

    Strips path components, replaces unsafe characters, limits length.

    Spec: Component 8 — sanitize_filename
    """
    if not user_filename:
        return "download"

    # Strip any path components (Unix and Windows)
    name = user_filename.replace("\\", "/").split("/")[-1]

    # Replace unsafe characters
    name = _SAFE_CHARS.sub("_", name)

    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name).strip("_")

    # Limit length
    if len(name) > _MAX_FILENAME_LENGTH:
        name = name[:_MAX_FILENAME_LENGTH]

    return name if name else "download"


def build_content_disposition(filename: str) -> str:
    """
    Build RFC 6266 Content-Disposition header value for attachment download.

    Spec: Component 8 — build_content_disposition
    """
    # ASCII-safe filename for Content-Disposition
    safe = _SAFE_CHARS.sub("_", filename)
    return f'attachment; filename="{safe}"'


def _clean_part(s: str) -> str:
    """Remove unsafe characters from a filename part."""
    return _SAFE_CHARS.sub("_", s).strip("_")[:60]


def _bbox_summary(bbox_str: str) -> str:
    """
    Create a compact bbox string for filenames.

    Converts '1.5,2.5,3.5,4.5' to 'bbox_1p5_2p5_3p5_4p5'.
    """
    try:
        parts = [float(x.strip()) for x in bbox_str.split(",")]
        if len(parts) == 4:
            formatted = "_".join(f"{v:.1f}".replace(".", "p").replace("-", "n") for v in parts)
            return f"bbox_{formatted}"
    except (ValueError, AttributeError):
        pass
    return "bbox"

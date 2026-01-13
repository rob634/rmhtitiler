# TiTiler URL Configuration Guide

Reference for generating TiTiler preview URLs based on COG band statistics.

## Base URL Pattern

```
{titiler_base}/cog/WebMercatorQuad/map.html?url={cog_url}&{params}
```

## Decision Tree

```
COG Analysis
    │
    ├── Band Count = 1
    │   ├── dtype = uint8 → Grayscale (no params needed)
    │   ├── dtype = float32/float64 → Continuous data
    │   │   ├── Is DEM/elevation? → colormap_name=terrain
    │   │   ├── Is NDVI/index? → colormap_name=rdylgn
    │   │   └── General → colormap_name=viridis
    │   └── Always add: rescale={min},{max}
    │
    ├── Band Count = 3
    │   ├── colorinterp = [red,green,blue] → No params needed
    │   ├── colorinterp = [blue,green,red] → bidx=3&bidx=2&bidx=1
    │   └── dtype != uint8 → Add rescale per band
    │
    └── Band Count = 4
        ├── colorinterp = [red,green,blue,alpha] → No params needed
        ├── colorinterp = [blue,green,red,alpha] → bidx=3&bidx=2&bidx=1&bidx=4
        └── 4th band NOT alpha → bidx=3&bidx=2&bidx=1 (exclude band 4)
```

## URL Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `url` | COG path (URL encoded) | `url=%2Fvsiaz%2Fbucket%2Ffile.tif` |
| `bidx` | Band index (1-based, repeat for multiple) | `bidx=3&bidx=2&bidx=1` |
| `rescale` | Min,max values for scaling | `rescale=0,255` or `rescale=272,505` |
| `colormap_name` | Named colormap for single-band | `colormap_name=terrain` |
| `nodata` | Override nodata value | `nodata=-9999` |
| `return_mask` | Include alpha mask | `return_mask=true` |

## Single-Band COGs (DEMs, Indices, Continuous Data)

### Required: Get Statistics First

```bash
curl "{titiler}/cog/statistics?url={cog_url}"
```

Response provides:
```json
{
  "b1": {
    "min": 272.0,
    "max": 505.0,
    "percentile_2": 276.0,
    "percentile_98": 362.0
  }
}
```

### Rescale Strategy

| Data Type | Rescale Value |
|-----------|---------------|
| Full range | `rescale={min},{max}` |
| Clip outliers | `rescale={percentile_2},{percentile_98}` |
| Known range (e.g., NDVI) | `rescale=-1,1` |

### Colormap Selection

| Data Type | Recommended Colormap |
|-----------|---------------------|
| DEM / Elevation | `terrain`, `gist_earth` |
| NDVI / Vegetation | `rdylgn`, `greens` |
| Temperature | `coolwarm`, `RdBu_r` |
| Generic continuous | `viridis`, `plasma`, `magma` |
| Bathymetry | `blues_r` |
| Categorical | `tab10`, `set1` |

### Example: DEM

```
Stats: min=272, max=505
URL: ?url={cog}&rescale=272,505&colormap_name=terrain
```

### Example: NDVI

```
Stats: min=-0.2, max=0.9
URL: ?url={cog}&rescale=-0.2,0.9&colormap_name=rdylgn
```

## Multi-Band COGs (RGB, RGBA)

### Band Order Detection

Check `colorinterp` from `/cog/info`:

| colorinterp | Action |
|-------------|--------|
| `[red, green, blue]` | No bidx needed |
| `[blue, green, red]` | `bidx=3&bidx=2&bidx=1` |
| `[red, green, blue, alpha]` | No bidx needed |
| `[blue, green, red, undefined]` | `bidx=3&bidx=2&bidx=1` (exclude bad alpha) |
| `[blue, green, red, alpha]` | `bidx=3&bidx=2&bidx=1&bidx=4` |

### Example: 4-Band BGR + undefined

```
Info: colorinterp=[blue,green,red,undefined], count=4
URL: ?url={cog}&bidx=3&bidx=2&bidx=1
```

### Example: Standard RGB

```
Info: colorinterp=[red,green,blue], count=3
URL: ?url={cog}  (no extra params)
```

## Algorithm for ETL Claude

```python
def generate_titiler_url(cog_info: dict, stats: dict, base_url: str, cog_url: str) -> str:
    """
    Generate TiTiler preview URL from COG metadata.

    Args:
        cog_info: Response from /cog/info
        stats: Response from /cog/statistics
        base_url: TiTiler base URL
        cog_url: Path to COG (will be URL encoded)
    """
    from urllib.parse import quote

    params = [f"url={quote(cog_url, safe='')}"]

    band_count = cog_info["count"]
    colorinterp = cog_info.get("colorinterp", [])
    dtype = cog_info["dtype"]

    if band_count == 1:
        # Single band - needs rescale and colormap
        b1_stats = stats["b1"]

        # Use percentiles to avoid outlier distortion
        min_val = b1_stats.get("percentile_2", b1_stats["min"])
        max_val = b1_stats.get("percentile_98", b1_stats["max"])
        params.append(f"rescale={min_val},{max_val}")

        # Choose colormap based on data characteristics
        if _is_elevation_data(cog_url, b1_stats):
            params.append("colormap_name=terrain")
        elif _is_vegetation_index(cog_url, b1_stats):
            params.append("colormap_name=rdylgn")
        else:
            params.append("colormap_name=viridis")

    elif band_count >= 3:
        # Multi-band - check band order
        if colorinterp[:3] == ["blue", "green", "red"]:
            # BGR order - reorder to RGB
            params.append("bidx=3&bidx=2&bidx=1")

            # Include alpha if valid
            if band_count == 4 and colorinterp[3] == "alpha":
                params.append("bidx=4")

        elif band_count == 4 and colorinterp[3] != "alpha":
            # 4th band is not alpha - exclude it
            if colorinterp[:3] == ["red", "green", "blue"]:
                params.append("bidx=1&bidx=2&bidx=3")
            else:
                params.append("bidx=3&bidx=2&bidx=1")

        # Rescale if not uint8
        if dtype not in ["uint8"]:
            for i in range(1, min(band_count, 3) + 1):
                b_stats = stats[f"b{i}"]
                min_val = b_stats.get("percentile_2", b_stats["min"])
                max_val = b_stats.get("percentile_98", b_stats["max"])
                params.append(f"rescale={min_val},{max_val}")

    return f"{base_url}/cog/WebMercatorQuad/map.html?{'&'.join(params)}"


def _is_elevation_data(url: str, stats: dict) -> bool:
    """Heuristic: DEM/DTM/elevation data."""
    url_lower = url.lower()
    keywords = ["dem", "dtm", "dsm", "elevation", "height", "terrain"]
    return any(kw in url_lower for kw in keywords)


def _is_vegetation_index(url: str, stats: dict) -> bool:
    """Heuristic: NDVI or vegetation index."""
    url_lower = url.lower()
    keywords = ["ndvi", "evi", "savi", "vegetation"]
    # Also check if range is roughly -1 to 1
    in_ndvi_range = stats["min"] >= -1.5 and stats["max"] <= 1.5
    return any(kw in url_lower for kw in keywords) or in_ndvi_range
```

## Quick Reference: Common Patterns

### DEM (float32, 1 band)
```
?url={cog}&rescale={min},{max}&colormap_name=terrain
```

### RGB Satellite (uint8, 3 bands, RGB order)
```
?url={cog}
```

### RGB Satellite (uint8, 3 bands, BGR order)
```
?url={cog}&bidx=3&bidx=2&bidx=1
```

### RGBA with bad 4th band (uint8, 4 bands, BGR + undefined)
```
?url={cog}&bidx=3&bidx=2&bidx=1
```

### NDVI (float32, 1 band)
```
?url={cog}&rescale=-1,1&colormap_name=rdylgn
```

### 16-bit RGB (uint16, 3 bands)
```
?url={cog}&rescale=0,65535&rescale=0,65535&rescale=0,65535
```

## Available Colormaps

Sequential: `viridis`, `plasma`, `inferno`, `magma`, `cividis`
Terrain: `terrain`, `gist_earth`, `cubehelix`
Diverging: `rdylgn`, `coolwarm`, `RdBu`, `RdBu_r`, `BrBG`
Categorical: `tab10`, `tab20`, `set1`, `set2`, `set3`
Ocean: `blues`, `blues_r`, `ocean`
Other: `rainbow`, `jet`, `turbo`, `gray`, `bone`

Full list: https://matplotlib.org/stable/gallery/color/colormap_reference.html

## API Endpoints Reference

| Endpoint | Purpose |
|----------|---------|
| `/cog/info?url=` | Band count, dtype, colorinterp, bounds |
| `/cog/statistics?url=` | Min, max, percentiles per band |
| `/cog/bounds?url=` | Geographic bounds |
| `/cog/WebMercatorQuad/tilejson.json?url=` | Tile metadata |
| `/cog/WebMercatorQuad/map.html?url=` | Interactive preview |
| `/cog/tiles/WebMercatorQuad/{z}/{x}/{y}?url=` | Individual tiles |

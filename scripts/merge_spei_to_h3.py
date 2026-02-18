"""Merge ERA5-Drought SPEI-12 annual aggregates onto H3 Level 5 hexagons.

For each year (2022-2024):
  1. Load 12 monthly SPEI-12 NetCDF grids
  2. Compute mean (average conditions) and min (worst month) per pixel
  3. Sample the nearest grid cell for each H3 hex centroid
  4. Add as new columns to the existing H3 parquet

Produces 6 columns:
  spei12_era5_2022_mean, spei12_era5_2023_mean, spei12_era5_2024_mean
  spei12_era5_2022_min,  spei12_era5_2023_min,  spei12_era5_2024_min

Usage:
    python scripts/merge_spei_to_h3.py <input_parquet> <output_parquet>
"""

import sys
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import xarray as xr

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
YEARS = [2022, 2023, 2024]


def load_yearly_grids(year: int) -> xr.DataArray:
    """Load 12 monthly SPEI-12 files into a single time-stacked DataArray."""
    files = sorted(DATA_DIR.glob(f"SPEI12_*_{year}??.nc"))
    if len(files) != 12:
        raise ValueError(f"Expected 12 files for {year}, found {len(files)}")
    ds = xr.open_mfdataset(files, combine="by_coords")
    return ds["SPEI12"].load()


def sample_grid_at_centroids(
    spei_grid: xr.DataArray, hex_ids: list[str]
) -> np.ndarray:
    """Sample nearest grid cell for each H3 hex centroid."""
    lats = np.empty(len(hex_ids))
    lngs = np.empty(len(hex_ids))
    for i, h in enumerate(hex_ids):
        lat, lng = h3.cell_to_latlng(h)
        lats[i] = lat
        lngs[i] = lng

    lat_da = xr.DataArray(lats, dims="hex")
    lon_da = xr.DataArray(lngs, dims="hex")

    sampled = spei_grid.sel(lat=lat_da, lon=lon_da, method="nearest")
    return sampled.values


def print_col_stats(name: str, values: np.ndarray):
    valid = values[np.isfinite(values)]
    realistic = valid[(valid > -10) & (valid < 10)]
    print(f"  {name}: valid={len(valid):,}  mean={np.mean(realistic):.3f}  "
          f"median={np.median(realistic):.3f}  "
          f"[P10={np.percentile(realistic, 10):.3f}, P90={np.percentile(realistic, 90):.3f}]")


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input_parquet> <output_parquet>")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    print(f"Reading parquet: {input_path}")
    df = pd.read_parquet(input_path)
    print(f"  {len(df):,} rows, {len(df.columns)} columns")

    hex_ids = df["h3_index"].tolist()

    for year in YEARS:
        print(f"\nProcessing {year}...")
        spei_all = load_yearly_grids(year)

        spei_mean = spei_all.mean(dim="time", skipna=True)
        spei_min = spei_all.min(dim="time", skipna=True)

        mean_vals = sample_grid_at_centroids(spei_mean, hex_ids)
        min_vals = sample_grid_at_centroids(spei_min, hex_ids)

        mean_col = f"spei12_era5_{year}_mean"
        min_col = f"spei12_era5_{year}_min"
        df[mean_col] = mean_vals
        df[min_col] = min_vals

        print_col_stats(mean_col, mean_vals)
        print_col_stats(min_col, min_vals)

    print(f"\nWriting parquet: {output_path}")
    df.to_parquet(output_path, index=False)
    print(f"  {len(df):,} rows, {len(df.columns)} columns")
    print("Done!")


if __name__ == "__main__":
    main()

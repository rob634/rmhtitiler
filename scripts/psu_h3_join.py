"""
Join PSU centroids to H3 parquet data (MENA client crop subset).

For each PSU point, computes the H3 Level 5 cell index from lat/lng,
then left-joins selected crop columns + SPEI scenarios from the H3
parquet dataset. Keeps all original point attributes.

Crops: wheat, citrus, olives (ooil), vegetables (vege/toma/onio),
       legumes (lent/chic/bean/opul)
Techs: a (all), i (irrigated), r (rainfed)
Metrics per crop/tech: harv_area_ha, phys_area_ha, production_mt, yield_kgha

Output: data/psu_h3_joined.csv
"""

import h3
import pandas as pd
import pyarrow.parquet as pq
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARQUET = ROOT / "data" / "mapspam2020_spei_h3level5_with_era5.parquet"
CSV_IN = ROOT / "centroids_for_merge.csv"
CSV_OUT = ROOT / "data" / "psu_h3_joined.csv"

H3_RES = 5

# Client crop subset for MENA
CLIENT_CROPS = ["whea", "citr", "ooil", "vege", "toma", "onio", "lent", "chic", "bean", "opul"]
TECHS = ["a", "i", "r"]
METRICS = ["harv_area_ha", "phys_area_ha", "production_mt", "yield_kgha"]

# SPEI scenario columns to include
SPEI_COLS = [
    "spei12_ssp585_median", "spei12_ssp585_p10",
    "spei12_ssp370_median", "spei12_ssp370_p10",
    "spei12_era5_2022_mean", "spei12_era5_2022_min",
    "spei12_era5_2023_mean", "spei12_era5_2023_min",
    "spei12_era5_2024_mean", "spei12_era5_2024_min",
]

# Build column list: h3_index + area_km2 + all crop/tech/metric combos + SPEI
keep_cols = ["h3_index", "area_km2"]
for crop in CLIENT_CROPS:
    for tech in TECHS:
        for metric in METRICS:
            keep_cols.append(f"{crop}_{tech}_{metric}")
keep_cols.extend(SPEI_COLS)

print(f"Reading PSU centroids from {CSV_IN}")
psu = pd.read_csv(CSV_IN)
print(f"  {len(psu)} points")

# Compute H3 index for each point (skip rows with missing coords)
def safe_h3(row):
    lat, lng = row["PSU_LATITUDE"], row["PSU_LONGITUDE"]
    if pd.isna(lat) or pd.isna(lng):
        return None
    return h3.latlng_to_cell(lat, lng, H3_RES)

psu["h3_index"] = psu.apply(safe_h3, axis=1)
missing = psu["h3_index"].isna().sum()
if missing:
    print(f"  {missing} points skipped (missing lat/lng)")

unique_h3 = psu["h3_index"].nunique()
print(f"  {unique_h3} unique H3 cells from {len(psu)} points")

print(f"Reading H3 parquet (selected columns only)")
schema = pq.read_schema(PARQUET)
available = set(schema.names)
actual_cols = [c for c in keep_cols if c in available]
missing_cols = [c for c in keep_cols if c not in available]
if missing_cols:
    print(f"  WARNING: {len(missing_cols)} columns not in parquet: {missing_cols[:5]}...")

h3_df = pq.read_table(PARQUET, columns=actual_cols).to_pandas()
print(f"  {len(h3_df)} rows, {len(actual_cols)} columns selected")

# Left join: keep all PSU rows, attach H3 data where available
merged = psu.merge(h3_df, on="h3_index", how="left")

matched = merged["area_km2"].notna().sum()
print(f"  {matched}/{len(psu)} points matched to H3 data")

# Summary per crop
print("\nCrop coverage (non-zero production in matched cells):")
for crop in CLIENT_CROPS:
    col = f"{crop}_a_production_mt"
    if col in merged.columns:
        nonzero = (merged[col].fillna(0) > 0).sum()
        print(f"  {crop:4s}  {nonzero:,} points with production")

merged.to_csv(CSV_OUT, index=False)
print(f"\nOutput: {CSV_OUT}")
print(f"  {len(merged)} rows, {len(merged.columns)} columns")
print(f"  Crops: {', '.join(CLIENT_CROPS)}")

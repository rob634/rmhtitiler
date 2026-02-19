"""
Convert PSU H3 joined CSV to Excel with a Data Dictionary tab.
"""

import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_IN = ROOT / "data" / "psu_h3_joined.csv"
XLSX_OUT = ROOT / "data" / "psu_h3_joined.xlsx"

CLIENT_CROPS = {
    "whea": "Wheat",
    "citr": "Citrus",
    "ooil": "Other Oilcrops (includes Olives)",
    "vege": "Vegetables",
    "toma": "Tomato",
    "onio": "Onion",
    "lent": "Lentil",
    "chic": "Chickpea",
    "bean": "Bean (includes Fava/Broad bean)",
    "opul": "Other Pulses",
}

TECHS = {
    "a": "All technologies combined",
    "i": "Irrigated only",
    "r": "Rainfed only",
}

METRICS = {
    "harv_area_ha": ("Harvested area", "hectares"),
    "phys_area_ha": ("Physical area", "hectares"),
    "production_mt": ("Production", "metric tonnes"),
    "yield_kgha": ("Yield", "kg per hectare"),
}

SPEI_DESCRIPTIONS = {
    "spei12_ssp585_median": "SPEI-12 projected 2050, SSP5-8.5 scenario, median across models",
    "spei12_ssp585_p10": "SPEI-12 projected 2050, SSP5-8.5 scenario, 10th percentile (driest)",
    "spei12_ssp370_median": "SPEI-12 projected 2050, SSP3-7.0 scenario, median across models",
    "spei12_ssp370_p10": "SPEI-12 projected 2050, SSP3-7.0 scenario, 10th percentile (driest)",
    "spei12_era5_2022_mean": "SPEI-12 observed (ERA5 reanalysis), 2022 annual mean",
    "spei12_era5_2022_min": "SPEI-12 observed (ERA5 reanalysis), 2022 worst month",
    "spei12_era5_2023_mean": "SPEI-12 observed (ERA5 reanalysis), 2023 annual mean",
    "spei12_era5_2023_min": "SPEI-12 observed (ERA5 reanalysis), 2023 worst month",
    "spei12_era5_2024_mean": "SPEI-12 observed (ERA5 reanalysis), 2024 annual mean",
    "spei12_era5_2024_min": "SPEI-12 observed (ERA5 reanalysis), 2024 worst month",
}

FIXED_COLS = {
    "_UUID": ("Internal UUID", "identifier", "PSU"),
    "UUID": ("UUID", "identifier", "PSU"),
    "ID": ("Numeric point ID", "integer", "PSU"),
    "PSU_LATITUDE": ("PSU centroid latitude", "decimal degrees (WGS84)", "PSU"),
    "PSU_LONGITUDE": ("PSU centroid longitude", "decimal degrees (WGS84)", "PSU"),
    "h3_index": ("H3 hexagonal cell index (resolution 5)", "H3 string", "H3 Join"),
    "area_km2": ("H3 cell area", "square kilometres", "H3 Cell"),
}


def build_dictionary(columns):
    rows = []
    for col in columns:
        if col in FIXED_COLS:
            desc, unit, group = FIXED_COLS[col]
            rows.append({"Column": col, "Group": group, "Description": desc, "Unit": unit})
            continue

        if col in SPEI_DESCRIPTIONS:
            rows.append({
                "Column": col, "Group": "Drought (SPEI-12)",
                "Description": SPEI_DESCRIPTIONS[col],
                "Unit": "SPEI index (< -1.5 = severe drought)",
            })
            continue

        # Parse crop_tech_metric pattern
        parts = col.split("_")
        if len(parts) >= 3:
            crop_code = parts[0]
            tech_code = parts[1]
            metric_key = "_".join(parts[2:])

            crop_name = CLIENT_CROPS.get(crop_code, crop_code)
            tech_name = TECHS.get(tech_code, tech_code)
            metric_desc, metric_unit = METRICS.get(metric_key, (metric_key, ""))

            rows.append({
                "Column": col,
                "Group": f"Crop: {crop_name}",
                "Description": f"{crop_name} — {tech_name} — {metric_desc}",
                "Unit": metric_unit,
            })
            continue

        rows.append({"Column": col, "Group": "Other", "Description": "", "Unit": ""})

    return pd.DataFrame(rows)


print(f"Reading {CSV_IN}")
df = pd.read_csv(CSV_IN)
print(f"  {len(df)} rows, {len(df.columns)} columns")

dictionary = build_dictionary(df.columns.tolist())

print(f"Writing {XLSX_OUT}")
with pd.ExcelWriter(XLSX_OUT, engine="openpyxl") as writer:
    df.to_excel(writer, sheet_name="PSU Data", index=False)
    dictionary.to_excel(writer, sheet_name="Data Dictionary", index=False)

    # Auto-size dictionary columns
    ws = writer.sheets["Data Dictionary"]
    for col_idx, col_name in enumerate(dictionary.columns, 1):
        max_len = max(
            len(str(col_name)),
            dictionary.iloc[:, col_idx - 1].astype(str).str.len().max(),
        )
        ws.column_dimensions[chr(64 + col_idx)].width = min(max_len + 3, 80)

size_mb = XLSX_OUT.stat().st_size / (1024 * 1024)
print(f"  Done: {size_mb:.1f} MB")
print(f"  Sheets: 'PSU Data' ({len(df)} rows), 'Data Dictionary' ({len(dictionary)} entries)")

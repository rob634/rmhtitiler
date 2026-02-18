"""Download SPEI-12 from ERA5-Drought (Copernicus CDS).

Downloads monthly SPEI-12 reanalysis for 2022-2024 at 0.25° resolution.
Requires ~/.cdsapirc with valid CDS API credentials.
"""

import cdsapi

client = cdsapi.Client()

print("Requesting SPEI-12 data for 2022-2024 from CDS...")
print("This may take several minutes (queued server-side).\n")

client.retrieve(
    "derived-drought-historical-monthly",
    {
        "variable": ["standardised_precipitation_evapotranspiration_index"],
        "product_type": ["reanalysis"],
        "accumulation_period": ["12"],
        "version": ["1_0"],
        "dataset_type": ["consolidated_dataset"],
        "year": ["2022", "2023", "2024"],
        "month": [
            "01", "02", "03", "04", "05", "06",
            "07", "08", "09", "10", "11", "12",
        ],
    },
    "data/spei12_era5_2022_2024.nc",
)

print("\nDone! Saved to data/spei12_era5_2022_2024.nc")

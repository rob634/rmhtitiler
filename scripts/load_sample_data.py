#!/usr/bin/env python3
"""Load sample STAC items into pgSTAC database."""

import asyncio
import asyncpg
import os
import json
from datetime import datetime

async def load_sample_data():
    """Load sample STAC collection and items."""

    database_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/pgstac")

    print(f"Connecting to database: {database_url}")
    conn = await asyncpg.connect(database_url)

    try:
        # Create collection
        collection = {
            "type": "Collection",
            "id": "namangan-imagery",
            "stac_version": "1.0.0",
            "description": "Namangan region imagery collection",
            "license": "proprietary",
            "extent": {
                "spatial": {"bbox": [[71.6, 40.9, 71.7, 41.1]]},
                "temporal": {"interval": [["2019-08-14T00:00:00Z", None]]}
            }
        }

        print(f"Creating collection: {collection['id']}")
        await conn.execute(
            "SELECT * FROM pgstac.create_collection($1::text::jsonb)",
            json.dumps(collection)
        )
        print(f"✓ Created collection: {collection['id']}")

        # Create sample item
        item = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "namangan-2019-08-14-R1C1",
            "collection": "namangan-imagery",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [71.6063, 40.9850],
                    [71.6681, 40.9850],
                    [71.6681, 41.0318],
                    [71.6063, 41.0318],
                    [71.6063, 40.9850]
                ]]
            },
            "bbox": [71.6063, 40.9850, 71.6681, 41.0318],
            "properties": {
                "datetime": "2019-08-14T00:00:00Z",
                "platform": "satellite",
                "instruments": ["camera"]
            },
            "assets": {
                "visual": {
                    "href": "/vsiaz/rmhazuregeobronze/namangan/namangan14aug2019_R1C1cog.tif",
                    "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                    "roles": ["data"],
                    "title": "RGB Visual"
                }
            },
            "links": []
        }

        print(f"Creating item: {item['id']}")
        await conn.execute(
            "SELECT * FROM pgstac.create_item($1::text::jsonb)",
            json.dumps(item)
        )
        print(f"✓ Created item: {item['id']}")

    finally:
        await conn.close()

    print("\n✅ Sample data loaded successfully")

if __name__ == "__main__":
    asyncio.run(load_sample_data())

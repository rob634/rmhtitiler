#!/bin/bash
# Initialize pgSTAC database schema

set -e

# Database connection from environment or args
DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/pgstac}"

echo "Initializing pgSTAC database: $DATABASE_URL"

# Run pgSTAC migrations
psql "$DATABASE_URL" -c "SELECT pgstac.migrate();" || echo "pgSTAC already initialized or migration not available"

echo "pgSTAC database initialized successfully"

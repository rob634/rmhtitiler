#!/bin/bash
set -e

echo "================================================"
echo "TiTiler with Azure Auth - Quick Start"
echo "================================================"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running"
    echo "Please start Docker Desktop and try again"
    exit 1
fi

echo "✅ Docker is running"
echo ""

# Create data directory if it doesn't exist
if [ ! -d "data" ]; then
    echo "📁 Creating data directory..."
    mkdir -p data
    echo "✅ Created data directory"
    echo ""
fi

# Check if data directory has any .tif files
if ! ls data/*.tif 1> /dev/null 2>&1; then
    echo "📥 No test COG files found in data directory"
    echo "Would you like to download a sample COG file? (y/n)"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        echo "Downloading sample COG from OpenAerialMap..."
        curl -L -o data/example.tif \
            "https://oin-hotosm.s3.us-east-1.amazonaws.com/5afeda152b6a08001185f11a/0/5afeda152b6a08001185f11b.tif"
        echo "✅ Sample COG downloaded to data/example.tif"
    else
        echo "⚠️  Please add your own COG files to the data/ directory"
    fi
    echo ""
fi

echo "🐳 Building and starting TiTiler container..."
echo "This may take a few minutes on first run..."
echo ""

# Build and start with docker-compose
docker-compose up --build -d

echo ""
echo "⏳ Waiting for server to start..."
sleep 5

# Wait for health check
MAX_ATTEMPTS=30
ATTEMPT=0
until curl -s http://localhost:8000/healthz > /dev/null 2>&1; do
    ATTEMPT=$((ATTEMPT + 1))
    if [ $ATTEMPT -ge $MAX_ATTEMPTS ]; then
        echo "❌ Server failed to start after 30 seconds"
        echo "Check logs with: docker-compose logs"
        exit 1
    fi
    echo -n "."
    sleep 1
done

echo ""
echo ""
echo "================================================"
echo "✅ TiTiler is running!"
echo "================================================"
echo ""
echo "🌐 Server URL: http://localhost:8000"
echo "📚 API Docs: http://localhost:8000/docs"
echo "💚 Health Check: http://localhost:8000/healthz"
echo ""
echo "================================================"
echo "Quick Test Commands:"
echo "================================================"
echo ""
echo "# Check health"
echo "curl http://localhost:8000/healthz | jq"
echo ""
echo "# Get COG info (if you downloaded the sample)"
echo "curl 'http://localhost:8000/cog/info?url=/data/example.tif' | jq"
echo ""
echo "# Get a tile"
echo "curl 'http://localhost:8000/cog/tiles/WebMercatorQuad/14/3876/6325?url=/data/example.tif' -o tile.png"
echo ""
echo "================================================"
echo "Useful Commands:"
echo "================================================"
echo ""
echo "# View logs"
echo "docker-compose logs -f"
echo ""
echo "# Stop server"
echo "docker-compose down"
echo ""
echo "# Restart server"
echo "docker-compose restart"
echo ""
echo "# Open API docs in browser (macOS)"
echo "open http://localhost:8000/docs"
echo ""
echo "================================================"
echo ""

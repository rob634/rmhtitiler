#!/bin/bash
# Script to explore TiTiler code inside the running container

echo "================================================"
echo "Exploring TiTiler Code in Container"
echo "================================================"
echo ""

# Check if container is running
if ! docker-compose ps | grep -q "Up"; then
    echo "❌ Container is not running"
    echo "Start it with: docker-compose up -d"
    exit 1
fi

echo "📦 TiTiler is installed in the container's Python environment"
echo ""
echo "Option 1: Open a shell in the container"
echo "----------------------------------------------"
echo "docker-compose exec titiler bash"
echo ""
echo "Then explore:"
echo "  python -c 'import titiler; print(titiler.__file__)'"
echo "  ls -la /usr/local/lib/python*/site-packages/titiler/"
echo ""
echo ""
echo "Option 2: View TiTiler's installed files"
echo "----------------------------------------------"
echo "Running now..."
echo ""

docker-compose exec titiler bash -c "
echo '📁 TiTiler installation location:'
python -c 'import titiler.core; print(titiler.core.__file__)'
echo ''
echo '📋 TiTiler modules:'
python -c 'import titiler; import os; print(os.listdir(os.path.dirname(titiler.__file__)))'
echo ''
echo '🔍 TilerFactory source file:'
python -c 'import titiler.core.factory; print(titiler.core.factory.__file__)'
echo ''
echo '📚 Available TiTiler components:'
python -c 'from titiler.core.factory import TilerFactory; import inspect; print(\"TilerFactory methods:\"); [print(f\"  - {m}\") for m in dir(TilerFactory) if not m.startswith(\"_\")]'
"

echo ""
echo "================================================"
echo "Option 3: View TiTiler source on GitHub"
echo "================================================"
echo "https://github.com/developmentseed/titiler"
echo ""

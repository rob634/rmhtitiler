"""
Entry point for running geotiler as a module.

Usage:
    python -m geotiler
    python -m geotiler --host 0.0.0.0 --port 8000
"""

import uvicorn


def main():
    """Run the application with uvicorn."""
    uvicorn.run(
        "geotiler.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()

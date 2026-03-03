"""
Entry point for running geotiler as a module.

Usage:
    python -m geotiler

Environment Variables:
    PORT: Server port (default: 8000)
"""

import os

import uvicorn


def main():
    """Run the application with uvicorn."""
    uvicorn.run(
        "geotiler.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    main()

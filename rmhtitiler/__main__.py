"""
Entry point for running rmhtitiler as a module.

Usage:
    python -m rmhtitiler
    python -m rmhtitiler --host 0.0.0.0 --port 8000
"""

import uvicorn


def main():
    """Run the application with uvicorn."""
    uvicorn.run(
        "rmhtitiler.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()

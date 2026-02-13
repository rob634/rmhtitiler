"""
Minimal preview server for the H3 explorer template.

Renders the template with mock values so you can review UI changes locally.
No database, no Azure auth, no DuckDB — just the HTML/CSS/JS.

Usage:
    python preview_h3.py
    Open http://localhost:8001/h3
"""

from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
import uvicorn

app = FastAPI()

templates_dir = Path(__file__).parent / "geotiler" / "templates"
static_dir = Path(__file__).parent / "geotiler" / "static"

templates = Jinja2Templates(directory=templates_dir)

if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/h3", response_class=HTMLResponse)
async def h3_preview(request: Request):
    return templates.TemplateResponse("pages/h3/explorer.html", {
        "request": request,
        "version": "preview",
        "nav_active": "/h3",
        "stac_api_enabled": False,
        "tipg_enabled": False,
        "h3_parquet_url": "",
        "h3_storage_token": "",
        "h3_auth_enabled": False,
        "h3_server_side": True,  # Server-side mode (no WASM download)
    })


if __name__ == "__main__":
    print("\n  H3 Explorer Preview: http://localhost:8001/h3\n")
    uvicorn.run(app, host="127.0.0.1", port=8001)

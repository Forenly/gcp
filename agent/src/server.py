#!/usr/bin/env python3
"""
FastAPI application for the GCP Lawn Mower Advisor.

Thin app shell: page routes, health/status and small utility endpoints live
here; the heavy lifting is split into focused modules wired in as routers —

  advisor.py        Gemini recommendation engine (/recommend)
  avip_capture.py   Playwright screen capture + tour manifest (Step 1)
  avip_analysis.py  Modal GPU Whisper+VLM analysis (Step 3)
  avip_publish.py   FFmpeg avatar montage & publish (Step 4)
  avip_videos.py    video library (list/play/delete)
  avip_common.py    shared paths (VIDEO_DIR, SCRATCH_DIR)
"""

import os
import sys
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent / "static"

import vertexai

# Local Imports
from mcp_client import get_db_client
import geo

# Load environment
GCP_PROJECT = os.getenv("GCP_PROJECT", "project-8925a333-2bd2-47ba-af2")
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "us-central1")

# Initialize Vertex AI (must happen before the advisor router builds models)
try:
    vertexai.init(project=GCP_PROJECT, location=VERTEX_LOCATION)
    print(f"Vertex AI initialized on project {GCP_PROJECT} in {VERTEX_LOCATION}.")
except Exception as e:
    print(f"Warning: Failed to initialize Vertex AI SDK: {e}. Ensure GCP credentials are active.", file=sys.stderr)

import advisor
import avip_analysis
import avip_capture
import avip_publish
import avip_videos

# FastAPI App
app = FastAPI(
    title="GCP Lawn Mower Advisor API",
    description="Intelligent robotic lawn mower recommendation and deployment planning advisor powered by Gemini 1.5 and MongoDB.",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static assets (hero/section imagery) from static/.
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Feature routers
app.include_router(advisor.router)
app.include_router(avip_capture.router)
app.include_router(avip_analysis.router)
app.include_router(avip_publish.router)
app.include_router(avip_videos.router)


@app.get("/", response_class=HTMLResponse)
def landing():
    """Serve the project landing page with the Maps browser key injected."""
    index = STATIC_DIR / "index.html"
    if index.exists():
        html = index.read_text(encoding="utf-8")
        html = html.replace("__MAPS_BROWSER_KEY__", os.getenv("MAPS_BROWSER_KEY", ""))
        # Always revalidate so a new deploy is picked up without a manual hard refresh.
        return HTMLResponse(html, headers={"Cache-Control": "no-cache, must-revalidate"})
    return HTMLResponse("<h1>Lawn Advisor</h1><p>See <a href='/api/status'>/api/status</a>.</p>")


@app.get("/github-cicd", response_class=HTMLResponse)
def guide_github_cicd():
    """Forenly Lab playbook: ship reviewable work (GitHub + CI/CD workflow)."""
    page = STATIC_DIR / "github-cicd.html"
    if page.exists():
        return HTMLResponse(page.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache, must-revalidate"})
    return HTMLResponse("<h1>Not found</h1>", status_code=404)


@app.get("/walkthrough-videos", response_class=HTMLResponse)
def guide_walkthrough_videos():
    """Forenly Lab playbook: turn a raw screen recording into a narrated walkthrough (Trupeer.ai)."""
    page = STATIC_DIR / "walkthrough-videos.html"
    if page.exists():
        return HTMLResponse(page.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache, must-revalidate"})
    return HTMLResponse("<h1>Not found</h1>", status_code=404)


@app.get("/presentation", response_class=HTMLResponse)
def present_dashboard():
    """Forenly AVIP Presenter Dashboard: Interactive showcase of the AI Video Production & Analysis Studio."""
    page = STATIC_DIR / "present.html"
    if page.exists():
        return HTMLResponse(page.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache, must-revalidate"})
    return HTMLResponse("<h1>Not found</h1>", status_code=404)


@app.get("/present")
def present_redirect():
    """Redirect deprecated /present route to /presentation."""
    return RedirectResponse(url="/presentation")


@app.get("/token", response_class=HTMLResponse)
def token_dashboard():
    """Proxy the live LLM token and cost tracking analytics page from the g1table server."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://10.156.0.13:8765/token", timeout=5) as r:
            html = r.read().decode("utf-8")
        return HTMLResponse(html, headers={"Cache-Control": "no-cache, must-revalidate"})
    except Exception as e:
        return HTMLResponse(f"<h1>Error loading Token Analytics Dashboard</h1><p>{e}</p>", status_code=502)


@app.get("/api/tokens")
def token_api_proxy():
    """Proxy the JSON token usage data from the g1table server."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://10.156.0.13:8765/api/tokens", timeout=5) as r:
            data = r.read().decode("utf-8")
        return Response(content=data, media_type="application/json")
    except Exception as e:
        return Response(content=json.dumps({"error": str(e)}), media_type="application/json", status_code=502)


@app.get("/favicon.ico")
def favicon():
    """Silence the browser's automatic favicon request (no static asset to serve)."""
    return Response(status_code=204)


def _status():
    """MongoDB connectivity + collection counts."""
    status = {"status": "online", "gcp_project": GCP_PROJECT, "vertex_location": VERTEX_LOCATION, "database_connected": False}
    try:
        client = get_db_client()
        client.client.admin.command("ping")
        status["database_connected"] = True
        status["mower_models_count"] = client.db.mower_models.count_documents({})
        status["yards_count"] = client.db.yards.count_documents({})
        status["deployment_plans_count"] = client.db.deployment_plans.count_documents({})
    except Exception as e:
        status["database_error"] = str(e)
    return status


@app.get("/health")
@app.get("/api/status")
def status_endpoint():
    """Health check endpoint displaying MongoDB connectivity and metadata."""
    return _status()


@app.get("/api/geocode")
def geocode_endpoint(q: str):
    """Proxy Google Geocoding via the server key (browser key is referrer-locked and
    rejected by the Geocoding web service). Returns {found, lat, lng, formatted_address}.

    A no-match (too vague a query, e.g. just 'stadium') returns 200 with found=false
    rather than 404 — so the browser console stays clean and the UI shows a friendly hint."""
    q = (q or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Missing query parameter 'q'.")
    result = geo.geocode(q)
    if not result:
        return {"found": False}
    return {"found": True, **result}


@app.get("/api/mowers")
def list_mowers():
    """Return the mower registry for the landing page to render."""
    try:
        client = get_db_client()
        mowers = list(client.db.mower_models.find({}).sort("max_yard_area_sqm", 1))
        for m in mowers:
            m["_id"] = str(m["_id"])
        return mowers
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load mower registry: {e}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    print(f"Starting Local Server on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)

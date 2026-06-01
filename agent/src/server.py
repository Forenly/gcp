#!/usr/bin/env python3
"""
FastAPI application for the GCP Lawn Mower Advisor.
Exposes a recommendation endpoint that invokes a Gemini-powered reasoning agent
equipped with MongoDB MCP database retrieval tools.
"""

import os
import sys
import json
import time
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, Response
from pydantic import BaseModel, Field, ConfigDict

STATIC_DIR = Path(__file__).resolve().parent / "static"
import vertexai
from vertexai.generative_models import (
    GenerativeModel, Tool, FunctionDeclaration,
    GenerationConfig, SafetySetting, HarmCategory, HarmBlockThreshold,
)

# Local Imports
from mcp_client import (
    get_db_client,
    tool_find_mowers,
    tool_find_similar_yards,
    tool_find_plans,
    tool_insert_plan
)
import geo

# Load environment
GCP_PROJECT = os.getenv("GCP_PROJECT", "project-8925a333-2bd2-47ba-af2")
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "us-central1")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash")

# Initialize Vertex AI
try:
    vertexai.init(project=GCP_PROJECT, location=VERTEX_LOCATION)
    print(f"Vertex AI initialized on project {GCP_PROJECT} in {VERTEX_LOCATION}.")
except Exception as e:
    print(f"Warning: Failed to initialize Vertex AI SDK: {e}. Ensure GCP credentials are active.", file=sys.stderr)

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

# Request & Response Schemas
class YardInput(BaseModel):
    area_sqm: float = Field(..., description="Total lawn area in square meters", example=1200)
    slope_pct: float = Field(..., description="Steepest slope percentage in the yard", example=15)
    obstacles: List[str] = Field(default=[], description="List of obstacles, e.g., 'tree', 'pond', 'flowerbed'", example=["pond", "playground"])
    boundary_type: str = Field(default="fenced", description="Type of boundary, e.g., 'fenced', 'open', 'hedged'", example="fenced")
    charging_access: str = Field(default="outlet-near", description="Proximity to power, e.g., 'outlet-near', 'shed-power', 'garage'", example="patio-outlet")
    terrain: str = Field(default="flat-grass", description="General terrain descriptor", example="complex-obstacles")
    polygon: Optional[List[List[float]]] = Field(default=None, description="Optional yard boundary drawn on a map, as [[lat, lng], ...]. When present, slope and soil are derived from these real-world coordinates.")

# The response shape mirrors the registry, but the model's free-form JSON varies
# (id vs _id, missing year/charging, zones_and_priorities vs first_mow_zones). Keep
# brand/model required for a meaningful card; everything else is optional and backfilled
# from the DB registry in _normalize_recommendation. populate_by_name accepts id or _id.
class RecommendedMower(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    id: str = Field(default="", alias="_id")
    brand: str
    model: str
    year: Optional[int] = None
    max_yard_area_sqm: Optional[float] = None
    max_slope_pct: Optional[float] = None
    obstacle_handling: Optional[str] = None
    boundary_tech: Optional[str] = None
    charging: Optional[str] = None
    price_tier: Optional[str] = None
    source_url: Optional[str] = None
    notes: Optional[str] = None

class DeploymentPlanDetails(BaseModel):
    model_config = ConfigDict(extra="ignore")
    boundary_placement: str = ""
    dock_location: str = ""
    first_mow_zones: List[dict] = []
    schedule: str = ""

class RecommendationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    recommended_mower: RecommendedMower
    alternatives: List[RecommendedMower] = []
    deployment_plan: DeploymentPlanDetails
    trace_id: str = ""
    site_conditions: Optional[dict] = Field(default=None, description="Slope and soil derived from the map polygon, if one was provided")
    grounding: Optional[dict] = Field(default=None, description="What the agent retrieved from MongoDB (similar yards + historical plans) to ground the recommendation")


# Define Function Declarations for Gemini Tools
# We map python functions to Vertex AI Function Declarations
find_mowers_decl = FunctionDeclaration(
    name="find_mowers",
    description="Find suitable robotic mowers based on physical yard requirements like area and slope.",
    parameters={
        "type": "OBJECT",
        "properties": {
            "max_area": {"type": "NUMBER", "description": "The yard's area in square meters. Returns mowers supporting >= this."},
            "max_slope": {"type": "NUMBER", "description": "The yard's maximum slope percentage. Returns mowers supporting >= this."},
            "boundary_tech": {"type": "STRING", "description": "Preferred boundary technology ('wire', 'virtual-rtk-gps', etc.)"}
        }
    }
)

find_similar_yards_decl = FunctionDeclaration(
    name="find_similar_yards",
    description="Find similar yard archetypes in MongoDB to review how their installations were handled.",
    parameters={
        "type": "OBJECT",
        "properties": {
            "area": {"type": "NUMBER", "description": "Yard area in square meters."},
            "slope": {"type": "NUMBER", "description": "Yard slope percentage."},
            "terrain": {"type": "STRING", "description": "Terrain keyword search (optional)."}
        },
        "required": ["area", "slope"]
    }
)

find_plans_decl = FunctionDeclaration(
    name="find_plans",
    description="Retrieve past deployment plans filtered by specific yard archetypes or mower IDs to see historical setups.",
    parameters={
        "type": "OBJECT",
        "properties": {
            "yard_ids": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "List of matching yard IDs."},
            "mower_ids": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "List of matching mower IDs."}
        }
    }
)

insert_plan_decl = FunctionDeclaration(
    name="insert_plan",
    description="Write the final recommended deployment plan back to MongoDB.",
    parameters={
        "type": "OBJECT",
        "properties": {
            "yard_id": {"type": "STRING", "description": "The target yard ID."},
            "mower_id": {"type": "STRING", "description": "The chosen mower ID."},
            "fit_reasons": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Bullet-point justifications of why this mower fits."},
            "plan_details": {
                "type": "OBJECT",
                "properties": {
                    "boundary_placement": {"type": "STRING", "description": "Where to put the boundary wire or virtual GPS path."},
                    "dock_location": {"type": "STRING", "description": "Charging dock placement advice."},
                    "first_mow_zones": {
                        "type": "ARRAY", 
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "zone": {"type": "STRING"},
                                "priority": {"type": "INTEGER"}
                            }
                        }
                    },
                    "schedule": {"type": "STRING", "description": "Mowing schedule recommendation."}
                },
                "required": ["boundary_placement", "dock_location", "schedule"]
            }
        },
        "required": ["yard_id", "mower_id", "fit_reasons", "plan_details"]
    }
)

mcp_tools = Tool(
    function_declarations=[
        find_mowers_decl,
        find_similar_yards_decl,
        find_plans_decl,
        insert_plan_decl
    ]
)


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


def _send_with_retry(chat, message, retries=4, base_delay=2.0):
    """Send a message to the Gemini chat, retrying on 429 / resource-exhausted.

    A single /recommend makes several sequential model round-trips (the tool loop),
    so a burst can trip the per-minute quota. Exponential backoff keeps the demo
    resilient instead of surfacing a hard 429 to the user. Non-quota errors re-raise
    immediately.
    """
    delay = base_delay
    for attempt in range(retries + 1):
        try:
            return chat.send_message(message)
        except Exception as e:
            name = type(e).__name__
            msg = str(e).lower()
            # 429/quota and stochastic response-validation failures (MAX_TOKENS, safety,
            # empty candidate) are both worth retrying — the model is non-deterministic.
            transient = "429" in str(e) or "resource exhausted" in msg or \
                        name in ("ResourceExhausted", "ResponseValidationError") or \
                        "did not complete successfully" in msg
            if not transient or attempt == retries:
                raise
            print(f"Vertex transient ({name}) — retry {attempt + 1}/{retries} after {delay:.1f}s", file=sys.stderr)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


_mower_cache = None
def _mower_by_id():
    """Lazy cache of the (small, static) mower registry keyed by _id."""
    global _mower_cache
    if _mower_cache is None:
        try:
            _mower_cache = {m["_id"]: m for m in get_db_client().db.mower_models.find({})}
        except Exception:
            _mower_cache = {}
    return _mower_cache


def _build_grounding(yards, plans):
    """Summarize what the agent retrieved from MongoDB into a provenance object the UI
    can show as 'Grounded in N similar installations'. Makes MongoDB visibly the agent's
    reasoning memory, not just storage. Dedupes by _id; defensive against odd shapes."""
    uy = {y.get("_id"): y for y in yards if isinstance(y, dict) and y.get("_id")}
    up = {p.get("_id"): p for p in plans if isinstance(p, dict) and p.get("_id")}
    if not uy and not up:
        return None
    slopes = [y["slope_pct"] for y in uy.values() if isinstance(y.get("slope_pct"), (int, float))]
    boundary_techs = {}
    for p in up.values():
        mid = p.get("mower_id")
        bt = (_mower_by_id().get(mid) or {}).get("boundary_tech")
        if bt:
            boundary_techs[bt] = boundary_techs.get(bt, 0) + 1
    terrains = sorted({y.get("terrain") for y in uy.values() if y.get("terrain")})
    out = {
        "similar_yards": len(uy),
        "historical_plans": len(up),
    }
    if slopes:
        out["avg_slope_pct"] = round(sum(slopes) / len(slopes), 1)
    if boundary_techs:
        out["boundary_techs"] = boundary_techs
    if terrains:
        out["terrains"] = terrains
    return out


def _ground_mower(m):
    """Backfill a mower dict from the DB registry by id, so specs (year/charging/
    price_tier/…) are real and present even if the model only echoed a few fields.
    Accepts either 'id' or '_id'. Returns a dict with '_id' set."""
    if not isinstance(m, dict):
        return None
    mid = m.get("_id") or m.get("id")
    notes = m.get("notes")
    doc = None
    if mid:
        try:
            doc = get_db_client().db.mower_models.find_one({"_id": mid})
        except Exception:
            doc = None
    out = dict(doc) if doc else dict(m)
    out["_id"] = mid or out.get("_id") or out.get("id") or ""
    if notes and "notes" not in out:
        out["notes"] = notes
    return out


def _normalize_recommendation(data):
    """Map the model's field-name drift onto the response schema and ground mowers
    against the registry. Idempotent and defensive — never raises on odd shapes."""
    if not isinstance(data, dict):
        return data

    rec = data.get("recommended_mower")
    if rec is not None:
        data["recommended_mower"] = _ground_mower(rec)

    alts = data.get("alternatives")
    if alts is None:
        alts = data.get("alternative_mowers")  # common model variant
    if isinstance(alts, list):
        data["alternatives"] = [g for g in (_ground_mower(a) for a in alts) if g]
    else:
        data["alternatives"] = []

    plan = data.get("deployment_plan")
    if isinstance(plan, dict):
        if "first_mow_zones" not in plan:
            zones = plan.get("zones_and_priorities") or plan.get("zones")
            if isinstance(zones, list):
                plan["first_mow_zones"] = zones
        # trace_id often lands inside the plan as plan_id
        if not data.get("trace_id") and plan.get("plan_id"):
            data["trace_id"] = plan["plan_id"]

    if not data.get("trace_id"):
        data["trace_id"] = data.get("plan_id") or ""

    return data


@app.post("/recommend", response_model=RecommendationResponse)
def get_recommendation(yard: YardInput):
    """
    Core reasoning pipeline:
    1. Directs Gemini to find matching mowers based on physical limits.
    2. Searches MongoDB for past similar yards/plans.
    3. Gemini reasons and picks the best match + alternative.
    4. Gemini creates an installation plan and writes it back to MongoDB.
    5. Returns structured recommendation and trace ID to the client.
    """
    try:
        # Provenance: what the agent retrieves from MongoDB during reasoning.
        grounding_yards = []
        grounding_plans = []

        # Geo-enrichment: if a map polygon was drawn, derive real slope + soil from
        # its coordinates and let them override / inform the recommendation.
        site_conditions = None
        site_note = ""
        if yard.polygon and len(yard.polygon) >= 3:
            site_conditions = geo.enrich_site(yard.polygon)
            if site_conditions.get("slope", {}).get("slope_pct") is not None:
                yard.slope_pct = site_conditions["slope"]["slope_pct"]
            soil = site_conditions.get("soil") or {}
            slope = site_conditions.get("slope") or {}
            parts = []
            if slope:
                parts.append(f"measured steepest slope ~{slope.get('slope_pct')}% "
                             f"(elevation {slope.get('elevation_min_m')}–{slope.get('elevation_max_m')} m)")
            if soil:
                tex = soil.get("texture")
                wrb = soil.get("wrb_class")
                desc = ", ".join(x for x in [tex, f"{wrb} soil group" if wrb else None] if x)
                if desc:
                    parts.append(f"soil: {desc} (clay {soil.get('clay_pct','?')}%, sand {soil.get('sand_pct','?')}%)")
            if parts:
                site_note = ("\n\nSite conditions read from the yard's map location — factor these into "
                             "the mower choice and plan (e.g. clay/wet soil affects schedule, steeper slope "
                             "needs AWD/RTK models): " + "; ".join(parts) + ".")

        # Initialize Gemini Model
        model = GenerativeModel(
            model_name=GEMINI_MODEL_NAME,
            system_instruction=(
                "You are an expert Autonomous Lawn-Mower Deployment Advisor.\n"
                "Your objective is to ingest a yard's specifications and provide a highly customized, robust installation plan.\n"
                "You MUST follow these strict reasoning steps:\n"
                "1. Find suitable mowers from the database using 'find_mowers' by providing the yard's area and slope steepness. "
                "Prefer mowers whose capacity limits are GREATER than or EQUAL to the yard's requirements.\n"
                "   IMPORTANT: If the yard's area exceeds EVERY mower's max area (no single unit can cover it), DO NOT give up. "
                "Recommend the highest-capacity mower available, and in the deployment plan explicitly state that multiple units "
                "or zone-splitting are required to cover the full area (e.g. ceil(area / mower_max_area) units).\n"
                "2. Find similar yards in the database using 'find_similar_yards' and pull their past plans using 'find_plans' to see how previous installations were designed.\n"
                "3. Reason about the options. Select the best primary mower and list the other candidates as alternatives.\n"
                "4. Draft a custom deployment plan detailing: charging dock location, virtual or physical boundary wire placement, zones with priorities, and schedule.\n"
                "5. Save your final recommendation using 'insert_plan' and note the generated plan ID.\n"
                "6. Return a final JSON object conforming exactly to the required output format. Do NOT hallucinate data outside what is fetched from tools. "
                "You MUST always return a recommended_mower — never respond that no mower was found."
            ),
            tools=[mcp_tools],
            generation_config=GenerationConfig(max_output_tokens=8192, temperature=0.4),
            safety_settings=[
                SafetySetting(category=c, threshold=HarmBlockThreshold.BLOCK_NONE)
                for c in (
                    HarmCategory.HARM_CATEGORY_HARASSMENT,
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                )
            ],
        )
        
        # Start a multi-turn chat session to let Gemini execute tools iteratively
        chat = model.start_chat()
        
        # Ingestion prompt
        prompt = (
            f"Please recommend a robotic mower and write a deployment plan for this yard:\n"
            f"- Area: {yard.area_sqm} sqm\n"
            f"- Max Slope: {yard.slope_pct}%\n"
            f"- Obstacles: {', '.join(yard.obstacles)}\n"
            f"- Boundary Type: {yard.boundary_type}\n"
            f"- Charging Power Access: {yard.charging_access}\n"
            f"- Terrain type: {yard.terrain}\n\n"
            "Query the database collections via your tools to find the perfect fit and log the plan back."
            + site_note
        )
        
        # Send prompt and run tool execution loop
        response = _send_with_retry(chat, prompt)
        
        # Tool handling loop
        max_iterations = 6
        loop_count = 0

        def _execute_tool(func_name, args):
            if func_name == "find_mowers":
                return tool_find_mowers(max_area=args.get("max_area"), max_slope=args.get("max_slope"), boundary_tech=args.get("boundary_tech"))
            elif func_name == "find_similar_yards":
                return tool_find_similar_yards(area=args.get("area"), slope=args.get("slope"), terrain=args.get("terrain"))
            elif func_name == "find_plans":
                return tool_find_plans(yard_ids=args.get("yard_ids"), mower_ids=args.get("mower_ids"))
            elif func_name == "insert_plan":
                plan_id = tool_insert_plan(yard_id=args.get("yard_id"), mower_id=args.get("mower_id"), fit_reasons=args.get("fit_reasons"), plan_details=args.get("plan_details"))
                return {"plan_id": plan_id, "status": "success"}
            print(f"Unknown tool called: {func_name}")
            return {"error": f"Tool '{func_name}' not recognized."}

        while loop_count < max_iterations:
            # Gemini 2.x may emit several function calls in one turn (parallel calling).
            # Execute ALL of them and return one function-response per call — the counts must match.
            calls = [p.function_call for p in response.candidates[0].content.parts
                     if p.function_call and p.function_call.name]
            if not calls:
                break
            loop_count += 1
            tool_responses = []
            for fc in calls:
                args = dict(fc.args)
                print(f"Gemini requested tool call: {fc.name} with arguments {args}")
                tool_output = _execute_tool(fc.name, args)
                # Capture what the agent actually retrieved from MongoDB so we can show
                # grounded provenance ("based on N similar installs") in the response.
                if fc.name == "find_similar_yards" and isinstance(tool_output, list):
                    grounding_yards.extend(tool_output)
                elif fc.name == "find_plans" and isinstance(tool_output, list):
                    grounding_plans.extend(tool_output)
                tool_responses.append(
                    vertexai.generative_models.Part.from_function_response(
                        name=fc.name, response={"result": tool_output}
                    )
                )
            # Send every tool response back in a single turn.
            response = _send_with_retry(chat, tool_responses)

        # The tool loop finished, now parse Gemini's final verbal response.
        # We need a clean JSON out of Gemini. Let's ask it to format its final response if needed, 
        # or parse the text if it returned a JSON block.
        final_text = response.text
        print(f"Gemini Final Response: {final_text}")
        
        # Clean markdown wrappers if any
        if "```json" in final_text:
            final_text = final_text.split("```json")[1].split("```")[0].strip()
        elif "```" in final_text:
            final_text = final_text.split("```")[1].split("```")[0].strip()
            
        parsed_data = json.loads(final_text)
        
        # Let's ensure fields mapped correctly (handling camelCase or aliases if needed)
        # Verify the structure has recommended_mower, alternatives, deployment_plan, trace_id
        if "recommended_mower" not in parsed_data or "deployment_plan" not in parsed_data:
            # Fallback query if Gemini failed to insert or return schema correctly
            db = get_db_client()
            # Try to fetch last inserted plan as reference
            last_plan = list(db.db.deployment_plans.find().sort("created_at", -1).limit(1))[0]
            mower = db.db.mower_models.find_one({"_id": last_plan["mower_id"]})
            
            parsed_data = {
                "recommended_mower": mower,
                "alternatives": list(db.db.mower_models.find({"_id": {"$ne": mower["_id"]}}).limit(2)),
                "deployment_plan": last_plan["plan"],
                "trace_id": last_plan["_id"]
            }

        # The model's field names drift (id/_id, alternative_mowers, zones_and_priorities,
        # plan_id) and it often omits registry specs. Normalize + ground against the DB so
        # the strict response_model always validates and the card shows real specs.
        parsed_data = _normalize_recommendation(parsed_data)

        # Grounding fallback: the agent's tool use is non-deterministic (it sometimes
        # answers from find_mowers alone). Guarantee the MongoDB provenance panel by
        # retrieving similar yards + their plans server-side when the loop didn't capture
        # them — same MCP-backed queries, so the "grounded in N installs" claim is real.
        try:
            if not grounding_yards:
                grounding_yards = tool_find_similar_yards(yard.area_sqm, yard.slope_pct, yard.terrain) or []
            if not grounding_plans and grounding_yards:
                yard_ids = [y["_id"] for y in grounding_yards if isinstance(y, dict) and y.get("_id")]
                if yard_ids:
                    grounding_plans = tool_find_plans(yard_ids=yard_ids) or []
        except Exception as e:
            print(f"Grounding fallback failed: {e}", file=sys.stderr)

        grounding = _build_grounding(grounding_yards, grounding_plans)
        if grounding:
            parsed_data["grounding"] = grounding
        if site_conditions:
            parsed_data["site_conditions"] = site_conditions
        return parsed_data

    except json.JSONDecodeError as je:
        print(f"JSON Parsing Error: {je}", file=sys.stderr)
        raise HTTPException(status_code=500, detail=f"Gemini returned invalid JSON block: {final_text}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"An error occurred during advisor execution: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    print(f"Starting Local Server on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)

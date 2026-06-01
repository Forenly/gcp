#!/usr/bin/env python3
"""
FastAPI application for the GCP Lawn Mower Advisor.
Exposes a recommendation endpoint that invokes a Gemini-powered reasoning agent
equipped with MongoDB MCP database retrieval tools.
"""

import os
import sys
import json
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, Response
from pydantic import BaseModel, Field

STATIC_DIR = Path(__file__).resolve().parent / "static"
import vertexai
from vertexai.generative_models import GenerativeModel, Tool, FunctionDeclaration

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

class RecommendedMower(BaseModel):
    id: str = Field(..., alias="_id")
    brand: str
    model: str
    year: int
    max_yard_area_sqm: float
    max_slope_pct: float
    obstacle_handling: str
    boundary_tech: str
    charging: str
    price_tier: str
    source_url: Optional[str] = None

class DeploymentPlanDetails(BaseModel):
    boundary_placement: str = Field(..., description="Where and how to layout boundaries (wire or virtual GPS)")
    dock_location: str = Field(..., description="Recommended location for the charging station")
    first_mow_zones: List[dict] = Field(..., description="Slicing the yard into initial zones with priority")
    schedule: str = Field(..., description="Suggested weekly or daily schedules")

class RecommendationResponse(BaseModel):
    recommended_mower: RecommendedMower
    alternatives: List[RecommendedMower] = []
    deployment_plan: DeploymentPlanDetails
    trace_id: str = Field(..., description="The ID of the generated deployment plan inserted in MongoDB")
    site_conditions: Optional[dict] = Field(default=None, description="Slope and soil derived from the map polygon, if one was provided")


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
        return HTMLResponse(html)
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
                "The mowers must have capacity limits GREATER than or EQUAL to the yard's requirements.\n"
                "2. Find similar yards in the database using 'find_similar_yards' and pull their past plans using 'find_plans' to see how previous installations were designed.\n"
                "3. Reason about the options. Select the best primary mower and list the other candidates as alternatives.\n"
                "4. Draft a custom deployment plan detailing: charging dock location, virtual or physical boundary wire placement, zones with priorities, and schedule.\n"
                "5. Save your final recommendation using 'insert_plan' and note the generated plan ID.\n"
                "6. Return a final JSON object conforming exactly to the required output format. Do NOT hallucinate data outside what is fetched from tools."
            ),
            tools=[mcp_tools]
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
        response = chat.send_message(prompt)
        
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
                tool_responses.append(
                    vertexai.generative_models.Part.from_function_response(
                        name=fc.name, response={"result": tool_output}
                    )
                )
            # Send every tool response back in a single turn.
            response = chat.send_message(tool_responses)

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

#!/usr/bin/env python3
"""
FastAPI application for the GCP Lawn Mower Advisor.
Exposes a recommendation endpoint that invokes a Gemini-powered reasoning agent
equipped with MongoDB MCP database retrieval tools.
"""

import os
import sys
import json
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
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

# Load environment
GCP_PROJECT = os.getenv("GCP_PROJECT", "project-8925a333-2bd2-47ba-af2")
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "us-central1")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash-001")

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


@app.get("/")
def read_root():
    """Health check endpoint displaying MongoDB connectivity and metadata."""
    status = {"status": "online", "gcp_project": GCP_PROJECT, "vertex_location": VERTEX_LOCATION, "database_connected": False}
    try:
        client = get_db_client()
        # Ping the server
        client.client.admin.command("ping")
        status["database_connected"] = True
        status["mower_models_count"] = client.db.mower_models.count_documents({})
        status["yards_count"] = client.db.yards.count_documents({})
        status["deployment_plans_count"] = client.db.deployment_plans.count_documents({})
    except Exception as e:
        status["database_error"] = str(e)
    return status


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
        )
        
        # Send prompt and run tool execution loop
        response = chat.send_message(prompt)
        
        # Tool handling loop
        max_iterations = 6
        loop_count = 0
        
        while response.candidates[0].content.parts[0].function_call and loop_count < max_iterations:
            loop_count += 1
            func_call = response.candidates[0].content.parts[0].function_call
            func_name = func_call.name
            args = dict(func_call.args)
            
            print(f"Gemini requested tool call: {func_name} with arguments {args}")
            
            # Execute python counterpart
            tool_output = None
            if func_name == "find_mowers":
                tool_output = tool_find_mowers(
                    max_area=args.get("max_area"),
                    max_slope=args.get("max_slope"),
                    boundary_tech=args.get("boundary_tech")
                )
            elif func_name == "find_similar_yards":
                tool_output = tool_find_similar_yards(
                    area=args.get("area"),
                    slope=args.get("slope"),
                    terrain=args.get("terrain")
                )
            elif func_name == "find_plans":
                tool_output = tool_find_plans(
                    yard_ids=args.get("yard_ids"),
                    mower_ids=args.get("mower_ids")
                )
            elif func_name == "insert_plan":
                plan_id = tool_insert_plan(
                    yard_id=args.get("yard_id"),
                    mower_id=args.get("mower_id"),
                    fit_reasons=args.get("fit_reasons"),
                    plan_details=args.get("plan_details")
                )
                tool_output = {"plan_id": plan_id, "status": "success"}
            else:
                print(f"Unknown tool called: {func_name}")
                tool_output = {"error": f"Tool '{func_name}' not recognized."}
                
            # Feed the output back into the chat session
            print(f"Sending tool output back to Gemini: {tool_output}")
            response = chat.send_message(
                vertexai.generative_models.Part.from_function_response(
                    name=func_name,
                    response={"result": tool_output}
                )
            )
            
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

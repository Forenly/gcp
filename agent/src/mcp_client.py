#!/usr/bin/env python3
"""
MongoDB Client & Tool Service.
Provides helper methods for querying mower models, yards, and deployment plans,
and implements standard MCP tools that can be registered in Vertex AI or exposed via MCP.
"""

import os
import sys
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB = os.getenv("MONGODB_DB", "lawn_advisor")

class DatabaseClient:
    """Helper client for interacting directly with the lawn database collections."""
    
    def __init__(self):
        if not MONGODB_URI:
            raise ValueError("MONGODB_URI is not set. Please set it in your environment or .env file.")
        
        self.client = MongoClient(MONGODB_URI)
        self.db = self.client[MONGODB_DB]
        
    def find_mower_models(self, max_area_sqm: float = None, max_slope_pct: float = None, boundary_tech: str = None) -> list:
        """
        Find suitable robotic mowers based on physical yard requirements.
        - max_area_sqm: The yard's area (mowers must support >= this area).
        - max_slope_pct: The yard's steepness (mowers must support >= this slope).
        - boundary_tech: Preference for physical wire or virtual boundaries.
        """
        query = {}
        
        if max_area_sqm is not None:
            # Mower max area must be greater than or equal to yard area
            query["max_yard_area_sqm"] = {"$gte": float(max_area_sqm)}
            
        if max_slope_pct is not None:
            # Mower max slope must be greater than or equal to yard slope
            query["max_slope_pct"] = {"$gte": float(max_slope_pct)}
            
        if boundary_tech:
            # Match boundary tech keyword, case-insensitive
            query["boundary_tech"] = {"$regex": boundary_tech, "$options": "i"}
            
        try:
            mowers = list(self.db.mower_models.find(query))
            # Convert ObjectId to string for JSON serialization
            for m in mowers:
                m["_id"] = str(m["_id"])
            return mowers
        except PyMongoError as e:
            print(f"Database error in find_mower_models: {e}", file=sys.stderr)
            return []

    def find_similar_yards(self, area_sqm: float, slope_pct: float, terrain: str = None) -> list:
        """
        Find similar yard archetypes in our system to reference past installations.
        Uses range queries on yard area (+/- 30%) and slope (+/- 15%) to match features.
        """
        area_min = area_sqm * 0.7
        area_max = area_sqm * 1.3
        slope_min = max(0, slope_pct - 15)
        slope_max = slope_pct + 15
        
        base_query = {
            "area_sqm": {"$gte": area_min, "$lte": area_max},
            "slope_pct": {"$gte": slope_min, "$lte": slope_max}
        }

        try:
            # Prefer a terrain match, but a tight terrain filter can return nothing
            # (the only matching archetype may be out of the area/slope band). Fall back
            # to area+slope similarity so the agent always has historical context to
            # reason over — and the grounding panel always has real installs to cite.
            yards = []
            if terrain:
                q = dict(base_query, terrain={"$regex": terrain, "$options": "i"})
                yards = list(self.db.yards.find(q).limit(5))
            if not yards:
                yards = list(self.db.yards.find(base_query).limit(5))
            for y in yards:
                y["_id"] = str(y["_id"])
            return yards
        except PyMongoError as e:
            print(f"Database error in find_similar_yards: {e}", file=sys.stderr)
            return []

    def find_past_plans(self, yard_ids: list = None, mower_ids: list = None) -> list:
        """
        Retrieve past deployment plans filtered by specific yard archetypes or mower IDs.
        Allows learning from previous successful schedules and boundary layouts.
        """
        query = {}
        if yard_ids:
            query["yard_id"] = {"$in": yard_ids}
        if mower_ids:
            query["mower_id"] = {"$in": mower_ids}
            
        try:
            plans = list(self.db.deployment_plans.find(query).sort("created_at", -1).limit(5))
            for p in plans:
                p["_id"] = str(p["_id"])
            return plans
        except PyMongoError as e:
            print(f"Database error in find_past_plans: {e}", file=sys.stderr)
            return []

    def insert_deployment_plan(self, yard_id: str, mower_id: str, fit_reasons: list, plan_details: dict) -> str:
        """
        Write a successful deployment plan recommendation record back to the database.
        Returns the generated plan ID.
        """
        # Formulate document matching schema in data/README.md
        import uuid
        plan_id = f"plan-{uuid.uuid4().hex[:6]}"
        
        doc = {
            "_id": plan_id,
            "yard_id": yard_id,
            "mower_id": mower_id,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "fit_reasons": fit_reasons,
            "plan": {
                "boundary_placement": plan_details.get("boundary_placement"),
                "dock_location": plan_details.get("dock_location"),
                "first_mow_zones": plan_details.get("first_mow_zones", []),
                "schedule": plan_details.get("schedule")
            }
        }
        
        try:
            self.db.deployment_plans.insert_one(doc)
            return plan_id
        except PyMongoError as e:
            print(f"Database error inserting deployment plan: {e}", file=sys.stderr)
            raise e

# Create a singleton instance to be imported by the FastAPI app or agent tools
_db_client = None

def get_db_client():
    global _db_client
    if _db_client is None:
        _db_client = DatabaseClient()
    return _db_client

# Expose standard functions for reasoning/tools usage
def tool_find_mowers(max_area: float = None, max_slope: float = None, boundary_tech: str = None):
    client = get_db_client()
    return client.find_mower_models(max_area_sqm=max_area, max_slope_pct=max_slope, boundary_tech=boundary_tech)

def tool_find_similar_yards(area: float, slope: float, terrain: str = None):
    client = get_db_client()
    return client.find_similar_yards(area_sqm=area, slope_pct=slope, terrain=terrain)

def tool_find_plans(yard_ids: list = None, mower_ids: list = None):
    client = get_db_client()
    return client.find_past_plans(yard_ids=yard_ids, mower_ids=mower_ids)

def tool_insert_plan(yard_id: str, mower_id: str, fit_reasons: list, plan_details: dict):
    client = get_db_client()
    return client.insert_deployment_plan(yard_id=yard_id, mower_id=mower_id, fit_reasons=fit_reasons, plan_details=plan_details)

if __name__ == "__main__":
    # Test connection and fetch counts if run directly
    print("Testing MongoDB Client wrapper...")
    try:
        c = DatabaseClient()
        mowers = c.find_mower_models()
        print(f"Connection OK! Found {len(mowers)} mowers in the database.")
    except Exception as e:
        print(f"Test connection failed: {e}")

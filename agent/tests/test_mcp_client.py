"""Unit tests for mcp_client.py — DatabaseClient query construction and the MCP
tool wrappers, with the Mongo collections faked (no live MongoDB).

Covers the terrain-lenient find_similar_yards fallback (regression for the
"tight terrain filter returns nothing" bug) and ObjectId→str serialization.
"""
import pytest
from pymongo.errors import PyMongoError

import mcp_client
from mcp_client import DatabaseClient


# ------------------------------------------------------------------ fakes

class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *_a, **_k):
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


class FakeColl:
    """Records every query; `responder(query)` decides what each find() returns."""

    def __init__(self, responder=lambda q: []):
        self.responder = responder
        self.queries = []
        self.inserted = []

    def find(self, query=None):
        self.queries.append(query or {})
        return FakeCursor([dict(d) for d in self.responder(query or {})])

    def insert_one(self, doc):
        self.inserted.append(doc)


class ErrorColl:
    def find(self, *_a, **_k):
        raise PyMongoError("boom")

    def insert_one(self, *_a, **_k):
        raise PyMongoError("boom")


def make_client(**colls):
    """DatabaseClient without __init__ (no MongoClient, no URI needed)."""
    c = DatabaseClient.__new__(DatabaseClient)

    class DB:
        pass

    db = DB()
    for name, coll in colls.items():
        setattr(db, name, coll)
    c.db = db
    return c


# ------------------------------------------------- find_mower_models

def test_find_mowers_query_construction():
    coll = FakeColl(lambda q: [{"_id": 123, "brand": "Husqvarna"}])
    c = make_client(mower_models=coll)
    out = c.find_mower_models(max_area_sqm=800, max_slope_pct=20, boundary_tech="wire")
    q = coll.queries[0]
    assert q["max_yard_area_sqm"] == {"$gte": 800.0}
    assert q["max_slope_pct"] == {"$gte": 20.0}
    assert q["boundary_tech"] == {"$regex": "wire", "$options": "i"}
    # ObjectId-ish _id must come back as a string for JSON serialization
    assert out[0]["_id"] == "123"


def test_find_mowers_no_filters_is_empty_query():
    coll = FakeColl(lambda q: [])
    c = make_client(mower_models=coll)
    c.find_mower_models()
    assert coll.queries[0] == {}


def test_find_mowers_db_error_returns_empty():
    c = make_client(mower_models=ErrorColl())
    assert c.find_mower_models(max_area_sqm=100) == []


# ----------------------------------------------- find_similar_yards

def test_similar_yards_range_bands():
    coll = FakeColl(lambda q: [{"_id": "y1"}])
    c = make_client(yards=coll)
    c.find_similar_yards(area_sqm=1000, slope_pct=20)
    q = coll.queries[0]
    assert q["area_sqm"] == {"$gte": 700.0, "$lte": 1300.0}   # ±30%
    assert q["slope_pct"] == {"$gte": 5, "$lte": 35}          # ±15 pts


def test_similar_yards_slope_band_floors_at_zero():
    coll = FakeColl(lambda q: [])
    c = make_client(yards=coll)
    c.find_similar_yards(area_sqm=500, slope_pct=4)
    assert coll.queries[0]["slope_pct"]["$gte"] == 0


def test_similar_yards_terrain_fallback():
    """Tight terrain filter returning nothing must fall back to area+slope only,
    so the grounding panel always has real installs to cite."""
    coll = FakeColl(lambda q: [] if "terrain" in q else [{"_id": "y9"}])
    c = make_client(yards=coll)
    out = c.find_similar_yards(area_sqm=1000, slope_pct=10, terrain="alpine-meadow")
    assert len(coll.queries) == 2                       # terrain try, then fallback
    assert "terrain" in coll.queries[0]
    assert "terrain" not in coll.queries[1]
    assert out == [{"_id": "y9"}]


def test_similar_yards_terrain_hit_skips_fallback():
    coll = FakeColl(lambda q: [{"_id": "y1"}] if "terrain" in q else [{"_id": "WRONG"}])
    c = make_client(yards=coll)
    out = c.find_similar_yards(area_sqm=1000, slope_pct=10, terrain="flat")
    assert len(coll.queries) == 1
    assert out == [{"_id": "y1"}]


# -------------------------------------------------- find_past_plans

def test_find_plans_filters_by_ids():
    coll = FakeColl(lambda q: [{"_id": "p1"}])
    c = make_client(deployment_plans=coll)
    c.find_past_plans(yard_ids=["y1", "y2"], mower_ids=["m1"])
    q = coll.queries[0]
    assert q["yard_id"] == {"$in": ["y1", "y2"]}
    assert q["mower_id"] == {"$in": ["m1"]}


def test_find_plans_db_error_returns_empty():
    c = make_client(deployment_plans=ErrorColl())
    assert c.find_past_plans(yard_ids=["y1"]) == []


# -------------------------------------------- insert_deployment_plan

def test_insert_plan_doc_shape_and_id():
    coll = FakeColl()
    c = make_client(deployment_plans=coll)
    pid = c.insert_deployment_plan(
        yard_id="y1", mower_id="m1", fit_reasons=["fits slope"],
        plan_details={"boundary_placement": "perimeter", "dock_location": "patio",
                      "first_mow_zones": [{"zone": "front", "priority": 1}],
                      "schedule": "Mon/Fri"})
    assert pid.startswith("plan-") and len(pid) == 11   # plan-<6 hex>
    doc = coll.inserted[0]
    assert doc["_id"] == pid
    assert doc["yard_id"] == "y1" and doc["mower_id"] == "m1"
    assert doc["plan"]["dock_location"] == "patio"
    assert doc["plan"]["first_mow_zones"] == [{"zone": "front", "priority": 1}]
    assert doc["created_at"].endswith("Z")


def test_insert_plan_db_error_raises():
    c = make_client(deployment_plans=ErrorColl())
    with pytest.raises(PyMongoError):
        c.insert_deployment_plan("y1", "m1", [], {})


# ------------------------------------------------------ tool wrappers

def test_tool_wrappers_delegate(monkeypatch):
    captured = {}

    class FakeDB:
        def find_mower_models(self, **kw):
            captured["mowers"] = kw
            return ["M"]

        def find_similar_yards(self, **kw):
            captured["yards"] = kw
            return ["Y"]

        def find_past_plans(self, **kw):
            captured["plans"] = kw
            return ["P"]

        def insert_deployment_plan(self, **kw):
            captured["insert"] = kw
            return "plan-xyz"

    monkeypatch.setattr(mcp_client, "get_db_client", lambda: FakeDB())
    assert mcp_client.tool_find_mowers(max_area=1, max_slope=2, boundary_tech="rtk") == ["M"]
    assert captured["mowers"] == {"max_area_sqm": 1, "max_slope_pct": 2, "boundary_tech": "rtk"}
    assert mcp_client.tool_find_similar_yards(area=1, slope=2, terrain="t") == ["Y"]
    assert mcp_client.tool_find_plans(yard_ids=["y"], mower_ids=None) == ["P"]
    assert mcp_client.tool_insert_plan("y", "m", ["r"], {"schedule": "s"}) == "plan-xyz"
    assert captured["insert"]["plan_details"] == {"schedule": "s"}

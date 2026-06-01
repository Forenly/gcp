"""Integration tests for the FastAPI app via TestClient.

Hermetic: MongoDB, Google Maps and Gemini are monkeypatched. These exercise the
real request/response wiring — routing, status codes, key injection, the geocode
proxy, and the polygon → enrichment → site_conditions passthrough in /recommend.
"""
import json
import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def client():
    return TestClient(server.app)


# ------------------------------------------------------------------- landing

def test_landing_injects_browser_key(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    # Placeholder must be substituted, and the raw token must not leak through.
    assert "__MAPS_BROWSER_KEY__" not in r.text
    assert r.headers.get("cache-control") == "no-cache, must-revalidate"


def test_favicon_is_204(client):
    assert client.get("/favicon.ico").status_code == 204


# ------------------------------------------------------------------- status

def test_status_shape(client, monkeypatch):
    class FakeAdmin:
        def command(self, *_):
            return {"ok": 1}

    class FakeClient:
        class client:
            admin = FakeAdmin()

        class db:
            class _Coll:
                @staticmethod
                def count_documents(_):
                    return 7
            mower_models = _Coll()
            yards = _Coll()
            deployment_plans = _Coll()

    monkeypatch.setattr(server, "get_db_client", lambda: FakeClient())
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["database_connected"] is True
    assert body["mower_models_count"] == 7


# ------------------------------------------------------------------ geocode

def test_geocode_endpoint_ok(client, monkeypatch):
    monkeypatch.setattr(server.geo, "geocode",
                        lambda q: {"lat": 51.5, "lng": -0.12, "formatted_address": "London, UK"})
    r = client.get("/api/geocode", params={"q": "London"})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["formatted_address"] == "London, UK"


def test_geocode_endpoint_empty_is_400(client):
    assert client.get("/api/geocode", params={"q": "  "}).status_code == 400


def test_geocode_endpoint_not_found_is_200_found_false(client, monkeypatch):
    # Vague query (e.g. just "stadium") → 200 + found:false, NOT a console-noisy 404.
    monkeypatch.setattr(server.geo, "geocode", lambda q: None)
    r = client.get("/api/geocode", params={"q": "stadium"})
    assert r.status_code == 200
    assert r.json() == {"found": False}


# ------------------------------------------------------------------ /recommend

class _FakePart:
    function_call = None  # no tool calls → loop breaks immediately


class _FakeResponse:
    def __init__(self, text):
        self._text = text

        class _Content:
            parts = [_FakePart()]

        class _Cand:
            content = _Content()

        self.candidates = [_Cand()]

    @property
    def text(self):
        return self._text


_FINAL_JSON = json.dumps({
    "recommended_mower": {
        "_id": "luba2", "brand": "Mammotion", "model": "Luba 2 AWD 5000", "year": 2024,
        "max_yard_area_sqm": 5000, "max_slope_pct": 80, "obstacle_handling": "vision",
        "boundary_tech": "RTK", "charging": "auto-dock", "price_tier": "premium",
    },
    "alternatives": [],
    "deployment_plan": {
        "boundary_placement": "virtual RTK perimeter",
        "dock_location": "north patio outlet",
        "first_mow_zones": [{"zone": "front", "priority": 1}],
        "schedule": "Mon/Wed/Fri morning",
    },
    "trace_id": "plan_test_123",
})


class _FakeChat:
    def send_message(self, *_a, **_k):
        return _FakeResponse(_FINAL_JSON)


class _FakeModel:
    def __init__(self, *a, **k):
        pass

    def start_chat(self):
        return _FakeChat()


class _NoDB:
    """Fake get_db_client() return for /recommend tests: registry lookups miss, so
    normalization keeps the model's echoed mower fields without touching real Mongo."""
    class db:
        class mower_models:
            @staticmethod
            def find_one(_q):
                return None


def test_recommend_polygon_enrichment(client, monkeypatch):
    """A drawn polygon must trigger geo enrichment, override slope, and surface
    site_conditions in the response."""
    monkeypatch.setattr(server, "GenerativeModel", _FakeModel)
    monkeypatch.setattr(server, "get_db_client", lambda: _NoDB())
    monkeypatch.setattr(server.geo, "enrich_site", lambda poly: {
        "slope": {"slope_pct": 21.4, "elevation_min_m": 100, "elevation_max_m": 110, "samples": 5},
        "soil": {"wrb_class": "Kastanozems"},
        "centroid": {"lat": 37.7, "lng": -122.4},
    })
    r = client.post("/recommend", json={
        "area_sqm": 800, "slope_pct": 5, "obstacles": ["tree"],
        "polygon": [[37.7, -122.4], [37.7, -122.39], [37.71, -122.39], [37.71, -122.4]],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recommended_mower"]["brand"] == "Mammotion"
    assert body["site_conditions"]["slope"]["slope_pct"] == 21.4
    assert body["site_conditions"]["soil"]["wrb_class"] == "Kastanozems"


def test_send_with_retry_recovers_from_429(monkeypatch):
    monkeypatch.setattr(server.time, "sleep", lambda _s: None)  # no real waiting
    calls = {"n": 0}

    class Chat:
        def send_message(self, _msg):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("429 Resource exhausted. Please try again later.")
            return "ok"

    assert server._send_with_retry(Chat(), "hi", retries=4, base_delay=0) == "ok"
    assert calls["n"] == 3  # failed twice, succeeded on the third


def test_send_with_retry_recovers_from_response_validation(monkeypatch):
    monkeypatch.setattr(server.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    class ResponseValidationError(Exception):
        pass

    class Chat:
        def send_message(self, _msg):
            calls["n"] += 1
            if calls["n"] < 2:
                raise ResponseValidationError("The model response did not complete successfully.")
            return "ok"

    assert server._send_with_retry(Chat(), "hi", retries=3, base_delay=0) == "ok"
    assert calls["n"] == 2


def test_send_with_retry_reraises_non_quota(monkeypatch):
    monkeypatch.setattr(server.time, "sleep", lambda _s: None)

    class Chat:
        def send_message(self, _msg):
            raise ValueError("bad request — not a quota error")

    with pytest.raises(ValueError):
        server._send_with_retry(Chat(), "hi", retries=2, base_delay=0)


def test_send_with_retry_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr(server.time, "sleep", lambda _s: None)

    class Chat:
        def send_message(self, _msg):
            raise RuntimeError("429 resource exhausted")

    with pytest.raises(RuntimeError, match="429"):
        server._send_with_retry(Chat(), "hi", retries=2, base_delay=0)


def test_normalize_recommendation_maps_and_grounds(monkeypatch):
    full = {"_id": "mammotion-luba2-5000", "brand": "Mammotion", "model": "Luba 2 AWD 5000",
            "year": 2024, "max_yard_area_sqm": 5000, "max_slope_pct": 80,
            "obstacle_handling": "vision", "boundary_tech": "virtual-rtk-gps",
            "charging": "auto-dock", "price_tier": "premium"}

    class DB:
        class db:
            class mower_models:
                @staticmethod
                def find_one(q):
                    return full if q.get("_id") == "mammotion-luba2-5000" else None
    monkeypatch.setattr(server, "get_db_client", lambda: DB())

    raw = {
        "recommended_mower": {"id": "mammotion-luba2-5000", "brand": "Mammotion",
                              "model": "Luba 2 AWD 5000", "notes": "Two units needed."},
        "alternative_mowers": [{"id": "mammotion-luba2-5000", "brand": "X", "model": "Y"}],
        "deployment_plan": {"dock_location": "patio", "boundary_placement": "perimeter",
                            "zones_and_priorities": [{"zone": "front", "priority": 1}],
                            "plan_id": "plan-abc", "schedule": "Mon/Wed/Fri"},
    }
    out = server._normalize_recommendation(raw)
    # mower grounded from DB (year/charging/price_tier backfilled) + notes preserved + _id set
    assert out["recommended_mower"]["_id"] == "mammotion-luba2-5000"
    assert out["recommended_mower"]["year"] == 2024
    assert out["recommended_mower"]["charging"] == "auto-dock"
    assert out["recommended_mower"]["notes"] == "Two units needed."
    # alternative_mowers -> alternatives, also grounded
    assert out["alternatives"][0]["price_tier"] == "premium"
    # zones_and_priorities -> first_mow_zones; plan_id -> trace_id
    assert out["deployment_plan"]["first_mow_zones"] == [{"zone": "front", "priority": 1}]
    assert out["trace_id"] == "plan-abc"


def test_normalize_recommendation_handles_missing_db(monkeypatch):
    # If the id isn't in the registry, keep the model's own fields without raising.
    class DB:
        class db:
            class mower_models:
                @staticmethod
                def find_one(q):
                    return None
    monkeypatch.setattr(server, "get_db_client", lambda: DB())
    out = server._normalize_recommendation(
        {"recommended_mower": {"id": "unknown", "brand": "B", "model": "M"}})
    assert out["recommended_mower"]["_id"] == "unknown"
    assert out["recommended_mower"]["brand"] == "B"
    assert out["alternatives"] == []


def test_recommend_without_polygon_no_enrichment(client, monkeypatch):
    monkeypatch.setattr(server, "GenerativeModel", _FakeModel)
    monkeypatch.setattr(server, "get_db_client", lambda: _NoDB())

    def fail(_):
        raise AssertionError("enrich_site must not be called without a polygon")
    monkeypatch.setattr(server.geo, "enrich_site", fail)
    r = client.post("/recommend", json={"area_sqm": 800, "slope_pct": 12})
    assert r.status_code == 200, r.text
    assert r.json().get("site_conditions") is None

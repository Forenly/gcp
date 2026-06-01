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
    assert r.json()["formatted_address"] == "London, UK"


def test_geocode_endpoint_empty_is_400(client):
    assert client.get("/api/geocode", params={"q": "  "}).status_code == 400


def test_geocode_endpoint_not_found_is_404(client, monkeypatch):
    monkeypatch.setattr(server.geo, "geocode", lambda q: None)
    assert client.get("/api/geocode", params={"q": "zzzqxnotaplace"}).status_code == 404


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


def test_recommend_polygon_enrichment(client, monkeypatch):
    """A drawn polygon must trigger geo enrichment, override slope, and surface
    site_conditions in the response."""
    monkeypatch.setattr(server, "GenerativeModel", _FakeModel)
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


def test_recommend_without_polygon_no_enrichment(client, monkeypatch):
    monkeypatch.setattr(server, "GenerativeModel", _FakeModel)

    def fail(_):
        raise AssertionError("enrich_site must not be called without a polygon")
    monkeypatch.setattr(server.geo, "enrich_site", fail)
    r = client.post("/recommend", json={"area_sqm": 800, "slope_pct": 12})
    assert r.status_code == 200, r.text
    assert r.json().get("site_conditions") is None

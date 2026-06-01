"""Unit tests for geo.py — pure geometry/texture helpers, plus the external
service wrappers (geocode / slope / soil) with `requests` fully mocked.

These cover the geocode regression directly: the server-key geocode path must
parse Google's response shape and degrade gracefully on errors / missing key.
"""
import geo


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


# ---------------------------------------------------------------- pure helpers

def test_haversine_known_distance():
    # ~1 km north-south near the equator is ~111 m per 0.001 deg latitude.
    d = geo._haversine((0.0, 0.0), (0.01, 0.0))
    assert 1100 < d < 1115


def test_haversine_zero():
    assert geo._haversine((40.0, -3.0), (40.0, -3.0)) == 0.0


def test_centroid():
    poly = [[0, 0], [0, 4], [4, 4], [4, 0]]
    assert geo.centroid(poly) == [2.0, 2.0]


def test_texture_class_buckets():
    assert geo._texture_class(45, 10, 45) == "clay"
    assert geo._texture_class(5, 80, 15) == "sandy"
    assert geo._texture_class(10, 30, 60) == "silty"
    assert geo._texture_class(30, 40, 30) == "clay loam"
    assert geo._texture_class(10, 40, 50) in ("loam", "silty")


# -------------------------------------------------------------------- geocode

def test_geocode_success(monkeypatch):
    payload = {
        "status": "OK",
        "results": [{
            "geometry": {"location": {"lat": 48.8584, "lng": 2.2945}},
            "formatted_address": "Eiffel Tower, Paris, France",
        }],
    }
    monkeypatch.setattr(geo.requests, "get", lambda *a, **k: FakeResp(payload))
    out = geo.geocode("Eiffel Tower")
    assert out == {"lat": 48.8584, "lng": 2.2945,
                   "formatted_address": "Eiffel Tower, Paris, France"}


def test_geocode_zero_results(monkeypatch):
    monkeypatch.setattr(geo.requests, "get",
                        lambda *a, **k: FakeResp({"status": "ZERO_RESULTS", "results": []}))
    assert geo.geocode("zzz-not-a-place") is None


def test_geocode_request_denied(monkeypatch):
    # The exact bug we fixed: a referrer-restricted key is rejected by the web service.
    payload = {"status": "REQUEST_DENIED",
               "error_message": "API keys with referer restrictions cannot be used with this API."}
    monkeypatch.setattr(geo.requests, "get", lambda *a, **k: FakeResp(payload))
    assert geo.geocode("London") is None


def test_geocode_empty_query():
    assert geo.geocode("") is None
    assert geo.geocode("   ") is None
    assert geo.geocode(None) is None


def test_geocode_no_key(monkeypatch):
    monkeypatch.setattr(geo, "MAPS_SERVER_KEY", "")
    assert geo.geocode("Paris") is None


def test_geocode_network_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("connection reset")
    monkeypatch.setattr(geo.requests, "get", boom)
    assert geo.geocode("Paris") is None


# ----------------------------------------------------------------------- slope

def test_get_slope_computes_percent(monkeypatch):
    # 4 corners + centroid. Elevations chosen so the steepest pair is well-separated.
    poly = [[0.0, 0.0], [0.0, 0.001], [0.001, 0.001], [0.001, 0.0]]
    payload = {"status": "OK", "results": [
        {"elevation": 100.0}, {"elevation": 100.0},
        {"elevation": 110.0}, {"elevation": 110.0},
        {"elevation": 105.0},
    ]}
    monkeypatch.setattr(geo.requests, "get", lambda *a, **k: FakeResp(payload))
    out = geo.get_slope(poly)
    assert out is not None
    assert out["elevation_min_m"] == 100.0
    assert out["elevation_max_m"] == 110.0
    assert out["samples"] == 5
    assert out["slope_pct"] > 0


def test_get_slope_bad_polygon():
    assert geo.get_slope([[0, 0], [1, 1]]) is None  # < 3 points
    assert geo.get_slope(None) is None


def test_get_slope_api_error(monkeypatch):
    monkeypatch.setattr(geo.requests, "get",
                        lambda *a, **k: FakeResp({"status": "INVALID_REQUEST"}))
    assert geo.get_slope([[0, 0], [0, 1], [1, 1]]) is None


# ------------------------------------------------------------------------ soil

def test_get_soil_class_and_texture(monkeypatch):
    def fake_get(url, *a, **k):
        if "classification" in url:
            return FakeResp({"wrb_class_name": "Phaeozems"})
        return FakeResp({"properties": {"layers": [
            {"name": "clay", "depths": [{"values": {"mean": 200}}]},
            {"name": "sand", "depths": [{"values": {"mean": 500}}]},
            {"name": "silt", "depths": [{"values": {"mean": 300}}]},
        ]}})
    monkeypatch.setattr(geo.requests, "get", fake_get)
    out = geo.get_soil(41.0, -93.0)
    assert out["wrb_class"] == "Phaeozems"
    assert out["clay_pct"] + out["sand_pct"] + out["silt_pct"] == 100
    assert out["texture"] in ("loam", "sandy", "clay", "silty", "clay loam")


def test_get_soil_class_only_when_texture_null(monkeypatch):
    # SoilGrids properties (beta) often returns null means — class must still survive.
    def fake_get(url, *a, **k):
        if "classification" in url:
            return FakeResp({"wrb_class_name": "Kastanozems"})
        return FakeResp({"properties": {"layers": [
            {"name": "clay", "depths": [{"values": {"mean": None}}]},
        ]}})
    monkeypatch.setattr(geo.requests, "get", fake_get)
    out = geo.get_soil(37.7, -122.4)
    assert out == {"wrb_class": "Kastanozems"}


def test_get_soil_total_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("timeout")
    monkeypatch.setattr(geo.requests, "get", boom)
    assert geo.get_soil(0, 0) is None


# -------------------------------------------------------------------- enrich

def test_enrich_site_combines(monkeypatch):
    poly = [[0.0, 0.0], [0.0, 0.001], [0.001, 0.0]]
    monkeypatch.setattr(geo, "get_slope", lambda p: {"slope_pct": 21.4, "elevation_min_m": 100, "elevation_max_m": 110, "samples": 4})
    monkeypatch.setattr(geo, "get_soil", lambda lat, lon: {"wrb_class": "Phaeozems"})
    site = geo.enrich_site(poly)
    assert site["slope"]["slope_pct"] == 21.4
    assert site["soil"]["wrb_class"] == "Phaeozems"
    assert "centroid" in site and set(site["centroid"]) == {"lat", "lng"}


def test_enrich_site_bad_polygon():
    assert geo.enrich_site([[0, 0]]) == {}
    assert geo.enrich_site(None) == {}

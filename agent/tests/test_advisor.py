"""Direct unit tests for advisor.py helpers not already pinned via test_api.py:
the registry cache (_mower_by_id) and mower grounding edge cases (_ground_mower).
Hermetic — get_db_client is monkeypatched throughout.
"""
import advisor


class _DB:
    def __init__(self, docs):
        self._docs = {d["_id"]: d for d in docs}
        outer = self

        class db:
            class mower_models:
                @staticmethod
                def find(_q):
                    return list(outer._docs.values())

                @staticmethod
                def find_one(q):
                    return outer._docs.get(q.get("_id"))

        self.db = db


# --------------------------------------------------------- _mower_by_id

def test_mower_by_id_caches_registry(monkeypatch):
    calls = {"n": 0}

    def get_client():
        calls["n"] += 1
        return _DB([{"_id": "m1", "boundary_tech": "wire"}])

    monkeypatch.setattr(advisor, "get_db_client", get_client)
    monkeypatch.setattr(advisor, "_mower_cache", None)
    assert advisor._mower_by_id()["m1"]["boundary_tech"] == "wire"
    advisor._mower_by_id()
    assert calls["n"] == 1  # second call served from cache


def test_mower_by_id_db_failure_degrades_to_empty(monkeypatch):
    def boom():
        raise RuntimeError("no mongo")

    monkeypatch.setattr(advisor, "get_db_client", boom)
    monkeypatch.setattr(advisor, "_mower_cache", None)
    assert advisor._mower_by_id() == {}


# --------------------------------------------------------- _ground_mower

def test_ground_mower_non_dict_returns_none():
    assert advisor._ground_mower("luba2") is None
    assert advisor._ground_mower(None) is None


def test_ground_mower_backfills_from_registry(monkeypatch):
    full = {"_id": "m1", "brand": "Mammotion", "year": 2024, "charging": "auto-dock"}
    monkeypatch.setattr(advisor, "get_db_client", lambda: _DB([full]))
    out = advisor._ground_mower({"id": "m1", "notes": "two units"})
    assert out["year"] == 2024
    assert out["notes"] == "two units"   # model-added note survives grounding
    assert out["_id"] == "m1"


def test_ground_mower_db_down_keeps_model_fields(monkeypatch):
    def boom():
        raise RuntimeError("no mongo")

    monkeypatch.setattr(advisor, "get_db_client", boom)
    out = advisor._ground_mower({"id": "mX", "brand": "B", "model": "M"})
    assert out["_id"] == "mX" and out["brand"] == "B"


def test_ground_mower_no_id_keeps_fields_with_empty_id(monkeypatch):
    monkeypatch.setattr(advisor, "get_db_client", lambda: _DB([]))
    out = advisor._ground_mower({"brand": "B", "model": "M"})
    assert out["_id"] == ""
    assert out["brand"] == "B"


# ------------------------------------------- _normalize_recommendation edges

def test_normalize_non_dict_passthrough():
    assert advisor._normalize_recommendation(None) is None
    assert advisor._normalize_recommendation("oops") == "oops"


def test_normalize_zones_key_variant(monkeypatch):
    monkeypatch.setattr(advisor, "get_db_client", lambda: _DB([]))
    out = advisor._normalize_recommendation({
        "recommended_mower": {"id": "m1", "brand": "B", "model": "M"},
        "deployment_plan": {"zones": [{"zone": "back", "priority": 2}]},
        "plan_id": "plan-top",
    })
    assert out["deployment_plan"]["first_mow_zones"] == [{"zone": "back", "priority": 2}]
    assert out["trace_id"] == "plan-top"   # top-level plan_id fallback

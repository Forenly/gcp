#!/usr/bin/env python3
"""
Geo-enrichment tools for the Lawn Advisor.

Given a yard polygon drawn on a map (real-world lat/lng coordinates), derive the
site conditions the agent needs — steepest slope and soil — by querying
deterministic geospatial services:

  - slope : Google Elevation API (samples polygon vertices + centroid)
  - soil  : SoilGrids / ISRIC (WRB soil group + topsoil texture)

These are fast, grounded data sources — NOT runtime web scraping. Web search is
reserved as a fallback elsewhere, so enrichment stays within a couple of seconds.
"""

import os
import math
import requests

MAPS_SERVER_KEY = os.getenv("MAPS_SERVER_KEY", "")

ELEV_URL = "https://maps.googleapis.com/maps/api/elevation/json"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
SOIL_CLASS_URL = "https://rest.isric.org/soilgrids/v2.0/classification/query"
SOIL_PROP_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"


def geocode(address):
    """Resolve an address string to a lat/lng + formatted name via Google Geocoding.

    Done server-side with the (referrer-unrestricted) server key: the browser key
    is referrer-locked and Google rejects referrer keys on the Geocoding web service.
    Returns {"lat","lng","formatted_address"} or None.
    """
    address = (address or "").strip()
    if not address or not MAPS_SERVER_KEY:
        return None
    try:
        r = requests.get(GEOCODE_URL, params={"address": address, "key": MAPS_SERVER_KEY}, timeout=12)
        data = r.json()
        if data.get("status") != "OK" or not data.get("results"):
            return None
        top = data["results"][0]
        loc = top["geometry"]["location"]
        return {
            "lat": loc["lat"],
            "lng": loc["lng"],
            "formatted_address": top.get("formatted_address", address),
        }
    except Exception:
        return None


def _haversine(a, b):
    """Distance in metres between two (lat, lng) points."""
    R = 6371000.0
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(h)))


def centroid(polygon):
    n = len(polygon)
    return [sum(p[0] for p in polygon) / n, sum(p[1] for p in polygon) / n]


def get_slope(polygon):
    """Estimate the steepest slope (%) across the polygon from sampled elevations."""
    if not polygon or len(polygon) < 3 or not MAPS_SERVER_KEY:
        return None
    pts = list(polygon) + [centroid(polygon)]
    locs = "|".join(f"{p[0]},{p[1]}" for p in pts)
    try:
        r = requests.get(ELEV_URL, params={"locations": locs, "key": MAPS_SERVER_KEY}, timeout=12)
        data = r.json()
        if data.get("status") != "OK":
            return None
        elevs = [res["elevation"] for res in data["results"]]
    except Exception:
        return None
    steepest = 0.0
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            d = _haversine(pts[i], pts[j])
            if d < 3:  # too close — elevation noise, skip
                continue
            steepest = max(steepest, abs(elevs[i] - elevs[j]) / d * 100.0)
    return {
        "slope_pct": round(steepest, 1),
        "elevation_min_m": round(min(elevs), 1),
        "elevation_max_m": round(max(elevs), 1),
        "samples": len(pts),
    }


def _texture_class(clay, sand, silt):
    """Coarse USDA-triangle texture label from clay/sand/silt percentages."""
    if clay >= 40:
        return "clay"
    if sand >= 70 and clay < 15:
        return "sandy"
    if silt >= 50 and clay < 27:
        return "silty"
    if clay >= 27:
        return "clay loam"
    return "loam"


def get_soil(lat, lon):
    """WRB soil group + topsoil texture from SoilGrids (ISRIC). Returns None on failure."""
    out = {}
    try:
        j = requests.get(SOIL_CLASS_URL, params={"lon": lon, "lat": lat, "number_classes": 1}, timeout=15).json()
        if j.get("wrb_class_name"):
            out["wrb_class"] = j["wrb_class_name"]
    except Exception:
        pass
    try:
        params = [("lon", lon), ("lat", lat), ("depth", "0-5cm"), ("value", "mean"),
                  ("property", "clay"), ("property", "sand"), ("property", "silt")]
        j = requests.get(SOIL_PROP_URL, params=params, timeout=18).json()
        vals = {}
        for layer in j.get("properties", {}).get("layers", []):
            try:
                vals[layer["name"]] = layer["depths"][0]["values"]["mean"]
            except Exception:
                continue
        if {"clay", "sand", "silt"} <= set(vals) and all(vals[k] is not None for k in ("clay", "sand", "silt")):
            tot = vals["clay"] + vals["sand"] + vals["silt"]
            if tot > 0:
                clay, sand, silt = (vals[k] / tot * 100 for k in ("clay", "sand", "silt"))
                out["texture"] = _texture_class(clay, sand, silt)
                out["clay_pct"], out["sand_pct"], out["silt_pct"] = round(clay), round(sand), round(silt)
    except Exception:
        pass
    return out or None


def enrich_site(polygon):
    """Combined enrichment: slope + soil for a polygon. Returns a site-conditions dict."""
    if not polygon or len(polygon) < 3:
        return {}
    site = {}
    slope = get_slope(polygon)
    if slope:
        site["slope"] = slope
    c = centroid(polygon)
    site["centroid"] = {"lat": round(c[0], 6), "lng": round(c[1], 6)}
    soil = get_soil(c[0], c[1])
    if soil:
        site["soil"] = soil
    return site

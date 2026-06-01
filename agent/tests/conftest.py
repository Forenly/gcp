"""Shared pytest fixtures + path setup for the Lawn Advisor test suite.

Tests are hermetic: no network, no live MongoDB, no Vertex AI calls. External
services (Google Maps, SoilGrids, Gemini, Mongo) are monkeypatched per-test.
"""
import os
import sys
from pathlib import Path

# Make `import geo`, `import server`, ... resolve against agent/src.
SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

# Deterministic keys so code paths that gate on a key being present are exercised.
os.environ.setdefault("MAPS_SERVER_KEY", "test-server-key")
os.environ.setdefault("MAPS_BROWSER_KEY", "test-browser-key")

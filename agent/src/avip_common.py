"""Shared filesystem paths for the AVIP presentation pipeline modules."""
import os
from pathlib import Path

# Project-local video store (repo's data/videos) — the AVIP demo is self-contained
# and must not depend on directories of other apps on this VM.
VIDEO_DIR = Path(os.getenv("AVIP_VIDEO_DIR") or Path(__file__).resolve().parents[2] / "data" / "videos")

# Scratch workspace shared with the Modal GPU pipeline scripts (run_pipeline.py
# reads the video + tour manifest from here and writes its results back).
SCRATCH_DIR = Path("/home/macb/scratch")

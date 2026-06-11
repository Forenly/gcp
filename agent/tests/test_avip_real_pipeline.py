import os
import sys
import pytest
import subprocess
from pathlib import Path
from fastapi.testclient import TestClient

# Path setups
SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import server

# Create a fixture to mock heavy background tasks
@pytest.fixture(autouse=True)
def mock_subprocess_and_tasks(monkeypatch):
    # Mock subprocess.run inside standard library
    class MockCompletedProcess:
        returncode = 0
        stdout = "mocked stdout"
        stderr = ""
    
    def mock_run(cmd, *args, **kwargs):
        # Return success instantly
        return MockCompletedProcess()
    
    # Mock subprocess.Popen inside standard library
    class MockPopen:
        returncode = 0
        def wait(self):
            return 0
            
    def mock_popen(cmd, *args, **kwargs):
        return MockPopen()
        
    # Apply monkeypatches directly to standard subprocess module
    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(subprocess, "Popen", mock_popen)
    monkeypatch.setattr(Path, "exists", lambda self: True)

# Initialize TestClient after mocking
@pytest.fixture
def client():
    return TestClient(server.app)


def test_video_analysis_run_with_filename(client):
    # Trigger run with an existing recording filename
    response = client.post(
        "/api/video-analysis/run",
        json={"filename": "forenly_ai_recording.mp4"}
    )
    assert response.status_code == 200
    assert response.json()["status"] in ("initiated", "already_running")


def test_video_analysis_status(client):
    response = client.get("/api/video-analysis/run-status")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "logs" in data


def test_video_publish_run(client):
    # Trigger publish composite with an existing recording filename
    response = client.post(
        "/api/publish/run",
        json={
            "recording_file": "forenly_ai_recording.mp4",
            "output_file": "final_test_junit_recording.mp4"
        }
    )
    assert response.status_code == 200
    assert response.json()["status"] in ("started", "already_running")


def test_video_publish_status(client):
    response = client.get("/api/publish/status")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "logs" in data

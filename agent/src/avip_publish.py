"""Montage & Publish step (Step 4 in the /presentation UI).

FFmpeg composites the talking-avatar overlay onto the screen recording in
real time; the YouTube upload lines are simulated for the demo narrative.
"""
import subprocess
import time

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from avip_common import VIDEO_DIR

router = APIRouter()

_publish_status = {"status": "idle", "logs": []}


def run_publish_task(recording_file: str, output_file: str):
    global _publish_status
    _publish_status["status"] = "running"
    _publish_status["logs"] = []

    def log(msg):
        _publish_status["logs"].append(msg)
        print(f"[publish] {msg}")

    log("[FFmpeg] Initializing overlay filter parameters...")
    src_video = VIDEO_DIR / recording_file
    avatar_video = VIDEO_DIR / "talking_avatar_em3_8s.mp4"
    out_video = VIDEO_DIR / output_file

    if not src_video.exists():
        _publish_status["status"] = "failed"
        log(f"[Error] Source recording file {recording_file} not found.")
        return

    try:
        log("[FFmpeg] Compositing talking avatar over the screen recording (bottom-right)...")
        # FFmpeg command to scale avatar to width 240, preserve aspect ratio, overlay in bottom right, use shortest=1
        cmd = [
            "ffmpeg", "-y",
            "-i", str(src_video),
            "-stream_loop", "-1", "-i", str(avatar_video),
            "-filter_complex", "[1:v]scale=240:-1[avatar];[0:v][avatar]overlay=W-w-10:H-h-10:shortest=1",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(out_video)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            _publish_status["status"] = "failed"
            log(f"[Error] FFmpeg compilation failed with exit code {result.returncode}.")
            log(result.stderr[-1000:] if result.stderr else "No stderr")
            return

        log("[YouTube API] Validating OAuth 2.0 token credentials for channel: @LawnAdvisorAI.")
        time.sleep(1)
        log('[YouTube API] Uploading presentation: "Autonomous AI Lawn Setup Plan"...')
        time.sleep(1)
        log("[YouTube] Auto-published successfully! Video URL: https://youtu.be/YT-uX829aB")
        log("[System] Autonomous production pipeline finalized successfully!")
        _publish_status["status"] = "success"
    except Exception as e:
        _publish_status["status"] = "failed"
        log(f"[Error] Compilation failed: {e}")


class PublishRequest(BaseModel):
    recording_file: str
    output_file: str


@router.post("/api/publish/run")
def trigger_publish(req: PublishRequest, background_tasks: BackgroundTasks):
    global _publish_status
    if _publish_status.get("status") == "running":
        return {"status": "already_running"}
    _publish_status["status"] = "starting"
    _publish_status["logs"] = []
    background_tasks.add_task(run_publish_task, req.recording_file, req.output_file)
    return {"status": "started"}


@router.get("/api/publish/status")
def get_publish_status(offset: int = 0):
    global _publish_status
    return {
        "status": _publish_status["status"],
        "logs": _publish_status["logs"][offset:],
        "total": len(_publish_status["logs"])
    }

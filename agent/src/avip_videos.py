"""Video library endpoints for the /presentation pipeline (list / play / delete)."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from avip_common import VIDEO_DIR

router = APIRouter()


@router.get("/api/videos")
def list_videos():
    """List available synthesized and rendered MP4 videos sorted by modification time."""
    video_dir = VIDEO_DIR
    if not video_dir.exists():
        return []

    videos = []
    for p in video_dir.glob("*.mp4"):
        if p.is_file():
            stat = p.stat()
            name = p.name
            v_type = "Synthesis"
            if name.startswith("render_"):
                v_type = "Remotion Render"
            elif name.startswith("veo_"):
                v_type = "Veo Video"
            elif name == "talking_avatar.mp4":
                v_type = "Talking Avatar"
            elif name == "downloaded_video.mp4":
                v_type = "Original Recording"
            elif name == "forenly_mower_marketing.mp4":
                v_type = "Promo Video"

            videos.append({
                "filename": name,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "created_at": stat.st_mtime,
                "type": v_type
            })

    # Newest videos first
    videos.sort(key=lambda x: x["created_at"], reverse=True)
    return videos


@router.get("/api/videos/play/{filename}")
def play_video(filename: str):
    """Safely stream/serve a specific video from the public directory."""
    if ".." in filename or filename.startswith("/") or filename.startswith("\\"):
        raise HTTPException(status_code=400, detail="Invalid file name.")

    video_path = VIDEO_DIR / filename
    if not video_path.exists() or not video_path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found.")

    return FileResponse(video_path, media_type="video/mp4")


@router.delete("/api/videos/{filename}")
def delete_video(filename: str):
    """Safely delete a video from the public directory, preserving core assets."""
    if ".." in filename or filename.startswith("/") or filename.startswith("\\"):
        raise HTTPException(status_code=400, detail="Invalid file name.")

    # Protect the demo's core working files (players on /presentation depend on these)
    core_assets = [
        "forenly_ai_recording.mp4",
        "talking_avatar_em3_8s.mp4",
        "talking_avatar_em3_8s_audio_early_80ms.mp4",
        "talking_avatar_em3_8s_audio_late_80ms.mp4",
    ]
    if filename.lower() in core_assets:
        raise HTTPException(
            status_code=403,
            detail="The system's core working file cannot be deleted."
        )
    video_path = VIDEO_DIR / filename
    if not video_path.exists() or not video_path.is_file():
        raise HTTPException(status_code=404, detail="Video file to delete was not found.")

    try:
        video_path.unlink()
        return {"status": "success", "message": f"{filename} has been successfully deleted."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error occurred while deleting file: {e}")

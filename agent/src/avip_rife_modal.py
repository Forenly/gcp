"""
AVIP Avatar Frame Interpolator — RIFE on Modal A10G.

Takes a 25 FPS composited talking avatar and uses RIFE (Real-Time Intermediate Flow Estimation)
to double its frame rate to 50 FPS, yielding incredibly fluid neck, head, and posture movement.
Muxes original audio stream seamlessly.

Run:  modal run avip_rife_modal.py
"""
import modal

image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("ffmpeg", "git", "wget", "libgl1", "libglib2.0-0", "unzip")
    .pip_install(
        "torch==2.5.1",
        "torchvision==0.20.1",
        "numpy==1.23.5",
        "opencv-python-headless",
        "tqdm",
        "sk-video",
        "moviepy",
    )
    .run_commands(
        "git clone https://github.com/hzwer/Practical-RIFE.git /root/rife",
        "wget -q https://huggingface.co/hzwer/RIFE/resolve/main/RIFEv4.26_0921.zip -O /root/rife/model.zip",
        "unzip -o /root/rife/model.zip -d /root/rife/",
        "mkdir -p /root/rife/train_log",
        # Find where flownet.pkl is extracted and copy its parent folder contents into train_log/
        "FLOWNET_DIR=$(find /root/rife/ -name 'flownet.pkl' | head -n 1 | xargs dirname); "
        "if [ ! -z \"$FLOWNET_DIR\" ]; then "
        "  echo \"Found flownet.pkl in $FLOWNET_DIR, copying files to /root/rife/train_log/\"; "
        "  cp -r $FLOWNET_DIR/* /root/rife/train_log/; "
        "fi",
        "ls -la /root/rife/train_log/"
    )
)

app = modal.App("avip-avatar-rife", image=image)


@app.function(gpu="A10G", timeout=1800)
def interpolate(video_bytes: bytes, multi: int = 2) -> bytes:
    import os
    import subprocess

    os.chdir("/root/rife")
    with open("in.mp4", "wb") as f:
        f.write(video_bytes)

    print("🎞️  Extracting original audio track...")
    subprocess.run(["ffmpeg", "-y", "-i", "in.mp4", "-vn", "-acodec", "pcm_s16le", "audio.wav"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    print(f"🚀 Running RIFE Frame Interpolation (multi={multi})...")
    # Practical-RIFE's inference_video.py processes the video frame rate multiplication.
    # It takes --video, --multi, --output, etc.
    cmd = [
        "python3", "inference_video.py",
        "--video=in.mp4",
        f"--multi={multi}",
        "--output=out_raw.mp4"
    ]
    print(f"Executing: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

    print("🎞️  Merging interpolated video with original audio...")
    has_audio = os.path.exists("audio.wav") and os.path.getsize("audio.wav") > 1000
    
    cmd_mux = ["ffmpeg", "-y", "-i", "out_raw.mp4"]
    if has_audio:
        cmd_mux += ["-i", "audio.wav"]
    
    cmd_mux += [
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "17"
    ]
    
    if has_audio:
        cmd_mux += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
        
    cmd_mux += ["out_final.mp4"]
    
    print(f"Executing: {' '.join(cmd_mux)}")
    subprocess.run(cmd_mux, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    with open("out_final.mp4", "rb") as f:
        return f.read()


@app.local_entrypoint()
def main(
    src: str = "/home/macb/hackathons/gcp/data/videos/talking_avatar_em3_8s_composited.mp4",
    out: str = "/home/macb/hackathons/gcp/data/videos/talking_avatar_em3_8s_interpolated.mp4",
    multi: int = 2,
):
    import os

    if not os.path.exists(src):
        raise FileNotFoundError(f"Source video {src} not found!")

    with open(src, "rb") as f:
        vid_data = f.read()

    print(f"📤 Uploading {len(vid_data)} bytes of {src} to Modal A10G...")
    result = interpolate.remote(vid_data, multi)
    
    with open(out, "wb") as f:
        f.write(result)
        
    print(f"✅ RIFE Interpolation complete! Saved 50 FPS video to: {out} ({len(result)} bytes)")

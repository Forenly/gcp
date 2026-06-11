"""
AVIP Talking Avatar — Background Matting & Compositing on Modal.

Isolates the portrait narrator from the moving background of the diffusion model
using a SOTA foreground segmentation model (rembg/u2net), and composites them onto
a static high-resolution, premium background image (e.g. professional studio/office)
to eliminate all video diffusion background warping.

Inputs : input_video.mp4 (SOTA EchoMimicV3 video) + background.jpg (static BG)
Output : output_composited.mp4 (stabilized premium composite video)

Run:  modal run avip_matting_compositing.py
"""
import modal

image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("ffmpeg", "git", "wget", "libgl1", "libglib2.0-0")
    .pip_install(
        "torch==2.5.1",
        "torchvision==0.20.1",
        "numpy<2",
        "opencv-python-headless",
        "rembg",
        "pillow",
        "onnxruntime",
    )
    # Prefetch the u2net / rmbg model weight so it builds into the image cache
    .run_commands(
        "python -c \"from rembg import remove; import numpy as np; from PIL import Image; remove(np.zeros((256, 256, 3), dtype=np.uint8))\""
    )
)

app = modal.App("avip-avatar-matting", image=image)


@app.function(gpu="A10G", timeout=1800)
def composite_background(video_bytes: bytes, bg_bytes: bytes) -> bytes:
    import glob
    import os
    import subprocess
    from PIL import Image
    from rembg import remove, new_session
    import cv2

    os.chdir("/root")
    with open("in.mp4", "wb") as f:
        f.write(video_bytes)
    with open("bg.jpg", "wb") as f:
        f.write(bg_bytes)

    frames_in, frames_out = "/root/fin", "/root/fout"
    os.makedirs(frames_in, exist_ok=True)
    os.makedirs(frames_out, exist_ok=True)

    print("🖼️  Extracting frames + audio from source video...")
    subprocess.run(["ffmpeg", "-y", "-i", "in.mp4", "-qscale:v", "2", f"{frames_in}/f_%05d.jpg"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    subprocess.run(["ffmpeg", "-y", "-i", "in.mp4", "-vn", "-acodec", "pcm_s16le", "audio.wav"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    frame_files = sorted(glob.glob(f"{frames_in}/f_*.jpg"))
    if not frame_files:
        raise RuntimeError("No frames extracted from source video.")

    print(f"✨ Loading matting session and processing {len(frame_files)} frames...")
    session = new_session("u2net") # robust silhouette extraction
    
    # Load background image
    bg_img = Image.open("bg.jpg").convert("RGBA")

    for i, fp in enumerate(frame_files):
        # Open source frame
        src_img = Image.open(fp).convert("RGBA")
        
        # Ensure background matches frame dimensions
        bg_resized = bg_img.resize(src_img.size, Image.Resampling.LANCZOS)
        
        # Remove background (matting) - isolating the person
        fg_isolated = remove(src_img, session=session)
        
        # Composite foreground over static background
        composite_frame = Image.alpha_composite(bg_resized, fg_isolated).convert("RGB")
        
        # Save output frame
        composite_frame.save(os.path.join(frames_out, os.path.basename(fp)), "JPEG", quality=95)
        
        if i % 50 == 0:
            print(f"   ...Processed {i}/{len(frame_files)} frames")

    print("🎞️  Assembling final composite MP4 with original audio track...")
    has_audio = os.path.exists("audio.wav") and os.path.getsize("audio.wav") > 1000
    cmd = ["ffmpeg", "-y", "-framerate", "25", "-i", f"{frames_out}/f_%05d.jpg"]
    if has_audio:
        cmd += ["-i", "audio.wav"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17"]
    if has_audio:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["/root/out_composited.mp4"]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    with open("/root/out_composited.mp4", "rb") as f:
        return f.read()


@app.local_entrypoint()
def main(
    src: str = "/home/macb/hackathons/gcp/data/videos/talking_avatar_em3_8s.mp4",
    bg: str = "/home/macb/scratch/studio_bg.jpg",
    out: str = "/home/macb/hackathons/gcp/data/videos/talking_avatar_em3_8s_composited.mp4",
):
    import os
    # If custom studio background doesn't exist, create a default solid color/blurred background
    if not os.path.exists(bg):
        print(f"ℹ️  Custom background {bg} not found. Creating a dark executive gradient/solid background...")
        os.makedirs(os.path.dirname(bg), exist_ok=True)
        from PIL import Image, ImageDraw
        # Create a beautiful deep dark green/black executive gradient
        img = Image.new("RGB", (1024, 1024), color="#0F1411")
        draw = ImageDraw.Draw(img)
        # Add a soft ambient highlight in the center
        draw.ellipse([256, 256, 768, 768], fill="#141E1A")
        img.save(bg)

    with open(src, "rb") as f:
        vid_data = f.read()
    with open(bg, "rb") as f:
        bg_data = f.read()

    print(f"📤 Uploading {len(vid_data)} bytes video + {len(bg_data)} bytes background to Modal for compositing...")
    result = composite_background.remote(vid_data, bg_data)
    with open(out, "wb") as f:
        f.write(result)
    print(f"✅ Matting & Compositing complete! Saved output to: {out} ({len(result)} bytes)")

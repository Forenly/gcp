"""
AVIP Avatar HD upscaler — RealESRGAN x2 + GFPGAN on Modal A10G.

Hallo renders the diffusion talking portrait at 512x512 (soft). This takes that
video and upscales it to ~1024 HD: RealESRGAN x2 sharpens the whole frame
(scene/clothes) while GFPGAN restores the face, then audio is re-muxed.

Run:  modal run avip_upscale_modal.py
"""
import modal

GFPGAN_URL = "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth"
REALESRGAN_X2_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth"

image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("ffmpeg", "git", "wget", "libgl1", "libglib2.0-0")
    .pip_install(
        "torch==2.5.1",
        "torchvision==0.20.1",
        "numpy<2",
        "opencv-python-headless",
        "cython",
    )
    .run_commands(
        "pip install --no-build-isolation basicsr facexlib gfpgan realesrgan",
    )
    .run_commands(
        "mkdir -p /root/models",
        f"wget -q '{GFPGAN_URL}' -O /root/models/GFPGANv1.4.pth",
        f"wget -q '{REALESRGAN_X2_URL}' -O /root/models/RealESRGAN_x2plus.pth",
        "test $(stat -c%s /root/models/GFPGANv1.4.pth) -gt 100000000",
        "test $(stat -c%s /root/models/RealESRGAN_x2plus.pth) -gt 50000000",
        # torchvision>=0.17 removed transforms.functional_tensor that basicsr imports.
        "python -c \"import torchvision.transforms.functional as F, os; open(os.path.join(os.path.dirname(F.__file__), 'functional_tensor.py'), 'w').write('from torchvision.transforms.functional import rgb_to_grayscale\\n')\"",
    )
)

app = modal.App("avip-avatar-upscale", image=image)


@app.function(gpu="A10G", timeout=1800)
def upscale(video_bytes: bytes) -> bytes:
    import glob
    import os
    import subprocess

    import cv2
    from basicsr.archs.rrdbnet_arch import RRDBNet
    from gfpgan import GFPGANer
    from realesrgan import RealESRGANer

    os.chdir("/root")
    with open("in.mp4", "wb") as f:
        f.write(video_bytes)

    frames_in, frames_out = "/root/fin", "/root/fout"
    os.makedirs(frames_in, exist_ok=True)
    os.makedirs(frames_out, exist_ok=True)

    print("🖼️  Extracting frames + audio...")
    subprocess.run(["ffmpeg", "-y", "-i", "in.mp4", "-qscale:v", "2", f"{frames_in}/f_%05d.jpg"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    subprocess.run(["ffmpeg", "-y", "-i", "in.mp4", "-vn", "-acodec", "pcm_s16le", "audio.wav"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    print("✨ Loading RealESRGAN x2 + GFPGAN...")
    rrdb = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=2)
    bg = RealESRGANer(scale=2, model_path="/root/models/RealESRGAN_x2plus.pth", model=rrdb,
                      tile=400, tile_pad=10, pre_pad=0, half=True)
    restorer = GFPGANer(model_path="/root/models/GFPGANv1.4.pth", upscale=2,
                        arch="clean", channel_multiplier=2, bg_upsampler=bg)

    frame_files = sorted(glob.glob(f"{frames_in}/f_*.jpg"))
    print(f"🚀 Upscaling {len(frame_files)} frames to 2x HD...")
    for i, fp in enumerate(frame_files):
        img = cv2.imread(fp)
        _, _, restored = restorer.enhance(img, has_aligned=False, only_center_face=False, paste_back=True)
        cv2.imwrite(os.path.join(frames_out, os.path.basename(fp)), restored)
        if i % 100 == 0:
            print(f"   ...{i}/{len(frame_files)}")

    print("🎞️  Re-assembling HD video with audio...")
    has_audio = os.path.exists("audio.wav") and os.path.getsize("audio.wav") > 1000
    cmd = ["ffmpeg", "-y", "-framerate", "25", "-i", f"{frames_out}/f_%05d.jpg"]
    if has_audio:
        cmd += ["-i", "audio.wav"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17"]
    if has_audio:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += ["/root/out.mp4"]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    with open("/root/out.mp4", "rb") as f:
        return f.read()


@app.local_entrypoint()
def main(
    src: str = "/home/macb/hackathons/gcp/data/videos/talking_avatar_hallo512.mp4",
    out: str = "/home/macb/hackathons/gcp/data/videos/talking_avatar.mp4",
):
    with open(src, "rb") as f:
        vid = f.read()
    print(f"📤 Uploading {len(vid)} bytes Hallo video to Modal A10G for HD upscale...")
    result = upscale.remote(vid)
    with open(out, "wb") as f:
        f.write(result)
    print(f"✅ HD-upscaled talking avatar written: {out} ({len(result)} bytes)")

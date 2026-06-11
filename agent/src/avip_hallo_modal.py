"""
AVIP Talking Avatar — Hallo diffusion portrait animation on Modal A100.

SadTalker pastes an animated face onto a frozen body. Hallo is a diffusion
audio-driven portrait animator: from a single photo + audio it generates much
more natural, cinematic motion of the head, shoulders and hair together.

Note: Hallo is face/portrait centric — the output is a close-up talking portrait
(the café background/crossed arms are not preserved). Trade-off accepted for far
more lifelike motion.

Inputs : bahadir.jpg + tts_narration.wav
Output : talking_avatar.mp4 (diffusion talking portrait)

Run:  modal run avip_hallo_modal.py
"""
import modal

image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("ffmpeg", "git", "wget", "libgl1", "libglib2.0-0")
    .run_commands(
        "cd /root && git clone --depth 1 https://github.com/fudan-generative-vision/hallo.git",
        # Hallo pins an exact, mutually-compatible stack (torch 2.2.2 + xformers etc.)
        "cd /root/hallo && pip install -r requirements.txt",
        "pip install huggingface_hub==0.23.2",
    )
    # Pretrained bundle (~10GB: hallo unet, face_analysis, motion_module, sd-vae,
    # wav2vec, audio_separator). Isolated layer so it caches across runs.
    .run_commands(
        "cd /root/hallo && python -c \"from huggingface_hub import snapshot_download; snapshot_download(repo_id='fudan-generative-ai/hallo', local_dir='pretrained_models')\"",
        "test -f /root/hallo/pretrained_models/hallo/net.pth",
    )
)

app = modal.App("avip-hallo-avatar", image=image)


@app.function(gpu="A100-80GB", timeout=7200)
def animate(image_bytes: bytes, audio_bytes: bytes) -> bytes:
    import os
    import subprocess

    os.chdir("/root/hallo")
    with open("/root/face.png", "wb") as f:
        f.write(image_bytes)
    with open("/root/audio.wav", "wb") as f:
        f.write(audio_bytes)

    print("🎬 Running Hallo diffusion portrait animation on A100 GPU (this is slow)...")
    cmd = [
        "python", "scripts/inference.py",
        "--source_image", "/root/face.png",
        "--driving_audio", "/root/audio.wav",
        "--output", "/root/out.mp4",
    ]
    # inference.py imports the repo-root `hallo` package; cwd isn't on sys.path
    # when running a script, so put the repo root on PYTHONPATH explicitly.
    env = os.environ.copy()
    env["PYTHONPATH"] = "/root/hallo"
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    print(proc.stdout[-3000:])
    if proc.returncode != 0:
        tail = proc.stderr[-4000:]
        print("STDERR:\n" + tail)
        raise RuntimeError(f"Hallo failed (rc={proc.returncode}):\n{tail}")

    with open("/root/out.mp4", "rb") as f:
        return f.read()


@app.local_entrypoint()
def main(
    face: str = "/home/macb/scratch/bahadir.jpg",
    audio: str = "/home/macb/hackathons/gcp/data/videos/tts_narration.wav",
    out: str = "/home/macb/hackathons/gcp/data/videos/talking_avatar.mp4",
):
    with open(face, "rb") as f:
        img = f.read()
    with open(audio, "rb") as f:
        aud = f.read()
    print(f"📤 Uploading {len(img)} bytes image + {len(aud)} bytes audio to Modal A100...")
    result = animate.remote(img, aud)
    with open(out, "wb") as f:
        f.write(result)
    print(f"✅ Hallo diffusion talking portrait written: {out} ({len(result)} bytes)")

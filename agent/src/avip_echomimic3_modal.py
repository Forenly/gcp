"""
AVIP Talking Avatar — EchoMimicV3 (AAAI 2026) on Modal A100.

EchoMimicV3 is a 1.3B audio-driven human-animation diffusion model (Wan2.1-Fun
backbone). From a single photo + audio it produces natural head + upper-body
motion with far fewer artifacts than Hallo.

Flash variant: 8-step generation. Output length is capped by --video_length
(81 frames ≈ 3.2s), so a short clip is generated first to validate quality
cheaply; scale --video_length up (≈ duration*25) for the full narration.

Run:  modal run avip_echomimic3_modal.py            # ~3s quality test
      modal run avip_echomimic3_modal.py --seconds 30   # full clip (slow)
"""
import modal

image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("ffmpeg", "git", "wget", "libgl1", "libglib2.0-0")
    .pip_install(
        "torch==2.5.1",
        "torchvision==0.20.1",
        "numpy<2",
        "huggingface_hub",
    )
    .run_commands(
        "cd /root && git clone --depth 1 https://github.com/antgroup/echomimic_v3.git",
        "cd /root/echomimic_v3 && pip install -r requirements.txt",
    )
    # Model bundle: Wan2.1-Fun-1.3B backbone + EchoMimicV3 flash transformer +
    # chinese-wav2vec2 audio encoder. Isolated layer so it caches across runs.
    .run_commands(
        "python -c \"from huggingface_hub import snapshot_download as d; d('alibaba-pai/Wan2.1-Fun-V1.1-1.3B-InP', local_dir='/root/models/Wan2.1-Fun-V1.1-1.3B-InP')\"",
        "python -c \"from huggingface_hub import snapshot_download as d; d('BadToBest/EchoMimicV3', local_dir='/root/models/em3', allow_patterns=['echomimicv3-flash-pro/*'])\"",
        "python -c \"from huggingface_hub import snapshot_download as d; d('TencentGameMate/chinese-wav2vec2-base', local_dir='/root/models/chinese-wav2vec2-base')\"",
        "test $(stat -c%s /root/models/em3/echomimicv3-flash-pro/diffusion_pytorch_model.safetensors) -gt 1000000000",
    )
    # infer_flash.py imports pyloudnorm but it's missing from requirements.txt.
    .run_commands("pip install pyloudnorm")
)

app = modal.App("avip-echomimic3-avatar", image=image)

PROMPT = ("A young man wearing a grey shirt sits at a wooden cafe table and speaks "
          "to the camera, with natural, subtle head and upper-body movement, "
          "realistic, professional.")


@app.function(gpu="A100-80GB", timeout=7200)
def animate(image_bytes: bytes, audio_bytes: bytes, video_length: int) -> bytes:
    import glob
    import os
    import subprocess

    os.chdir("/root/echomimic_v3")
    with open("/root/face.jpg", "wb") as f:
        f.write(image_bytes)
    with open("/root/audio.wav", "wb") as f:
        f.write(audio_bytes)

    print(f"🎬 EchoMimicV3 Flash on A100 — video_length={video_length} frames (~{video_length/25:.1f}s)...")
    cmd = [
        "python", "infer_flash.py",
        "--image_path", "/root/face.jpg",
        "--audio_path", "/root/audio.wav",
        "--prompt", PROMPT,
        "--num_inference_steps", "8",
        "--config_path", "config/config.yaml",
        "--model_name", "/root/models/Wan2.1-Fun-V1.1-1.3B-InP",
        "--transformer_path", "/root/models/em3/echomimicv3-flash-pro/diffusion_pytorch_model.safetensors",
        "--wav2vec_model_dir", "/root/models/chinese-wav2vec2-base",
        "--sampler_name", "Flow_Unipc",
        "--video_length", str(video_length),
        "--guidance_scale", "6.0",
        "--audio_guidance_scale", "3.0",
        "--audio_scale", "1.0",
        "--seed", "43",
        "--enable_teacache",
        "--teacache_threshold", "0.1",
        "--weight_dtype", "bfloat16",
        "--sample_size", "768", "768",
        "--fps", "25",
        "--save_path", "/root/outputs",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = "/root/echomimic_v3"
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    print(proc.stdout[-3000:])
    if proc.returncode != 0:
        tail = proc.stderr[-4000:]
        print("STDERR:\n" + tail)
        raise RuntimeError(f"EchoMimicV3 failed (rc={proc.returncode}):\n{tail}")

    mp4s = glob.glob("/root/outputs/**/*.mp4", recursive=True) + glob.glob("/root/echomimic_v3/outputs/**/*.mp4", recursive=True)
    if not mp4s:
        raise RuntimeError("EchoMimicV3 produced no mp4 output")
    out_path = max(mp4s, key=os.path.getsize)
    print(f"📦 Selected output: {out_path}")
    with open(out_path, "rb") as f:
        return f.read()


@app.local_entrypoint()
def main(
    seconds: float = 3.2,
    face: str = "/home/macb/scratch/bahadir.jpg",
    audio: str = "/home/macb/hackathons/gcp/data/videos/tts_narration.wav",
    out: str = "/home/macb/hackathons/gcp/data/videos/talking_avatar_em3.mp4",
):
    video_length = int(round(seconds * 25))
    # round to 4n+1 (vae temporal compression friendly)
    video_length = ((video_length - 1) // 4) * 4 + 1
    with open(face, "rb") as f:
        img = f.read()
    with open(audio, "rb") as f:
        aud = f.read()
    print(f"📤 Uploading image + audio to Modal A100 (target {seconds}s = {video_length} frames)...")
    result = animate.remote(img, aud, video_length)
    with open(out, "wb") as f:
        f.write(result)
    print(f"✅ EchoMimicV3 clip written: {out} ({len(result)} bytes)")

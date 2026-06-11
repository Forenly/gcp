"""
AVIP Talking Avatar — SadTalker on Modal A10G GPU (HEAD MOTION + lip-sync).

Wav2Lip only animates the lips on a frozen photo. SadTalker drives the WHOLE
head from a single still image + audio: natural head pose motion, eye blinks
and lip-sync, then GFPGAN restores the face to HD.

Inputs : bahadir.jpg (still photo) + tts_narration.wav (TTS voice track)
Output : talking_avatar.mp4 (HD talking head WITH head movement)

Run:  modal run avip_sadtalker_modal.py
"""
import modal

image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("ffmpeg", "git", "wget", "libgl1", "libglib2.0-0")
    .pip_install(
        # torch 2.5.1: weights_only default is still False (2.6 flipped it) so
        # SadTalker's torch.load(.tar) checkpoints load without patching.
        "torch==2.5.1",
        "torchvision==0.20.1",
        # 1.23.5: SadTalker's legacy code uses np.float (removed in numpy 1.24).
        "numpy==1.23.5",
        "opencv-python-headless",
        "face_alignment==1.3.5",
        "imageio",
        "imageio-ffmpeg",
        "librosa==0.10.2",
        "numba",
        "resampy",
        "pydub",
        "scipy",
        "kornia",
        "yacs",
        "pyyaml",
        "joblib",
        "scikit-image",
        "tqdm",
        "av",
        "safetensors",
        "cython",
    )
    # gfpgan stack — basicsr is an sdist whose isolated build pulls a conflicting
    # CUDA metapackage; install without isolation so it reuses the pinned torch.
    .run_commands(
        "pip install --no-build-isolation basicsr facexlib gfpgan realesrgan",
    )
    .run_commands(
        "cd /root && git clone --depth 1 https://github.com/OpenTalker/SadTalker.git",
    )
    # Heavy checkpoint download isolated in its own layer so source patches below
    # can be tweaked without re-pulling ~2GB of weights.
    .run_commands(
        "cd /root/SadTalker && bash scripts/download_models.sh",
        "test $(stat -c%s /root/SadTalker/checkpoints/SadTalker_V0.0.2_512.safetensors) -gt 100000000",
    )
    .run_commands(
        # librosa>=0.10 made mel sr/n_fft keyword-only — patch SadTalker's audio util.
        r"sed -i 's/librosa\.filters\.mel(hp\.sample_rate, hp\.n_fft,/librosa.filters.mel(sr=hp.sample_rate, n_fft=hp.n_fft,/' /root/SadTalker/src/utils/audio.py",
        # torchvision>=0.17 removed transforms.functional_tensor that basicsr imports.
        "python -c \"import torchvision.transforms.functional as F, os; open(os.path.join(os.path.dirname(F.__file__), 'functional_tensor.py'), 'w').write('from torchvision.transforms.functional import rgb_to_grayscale\\n')\"",
    )
)

app = modal.App("avip-sadtalker-avatar", image=image)


@app.function(gpu="A10G", timeout=1800)
def talking_head(image_bytes: bytes, audio_bytes: bytes) -> bytes:
    import glob
    import os
    import subprocess

    os.chdir("/root/SadTalker")
    with open("/root/face.jpg", "wb") as f:
        f.write(image_bytes)
    with open("/root/audio.wav", "wb") as f:
        f.write(audio_bytes)

    print("🎬 Running SadTalker (head motion + lip-sync) on A10G GPU...")
    cmd = [
        "python", "inference.py",
        "--driven_audio", "/root/audio.wav",
        "--source_image", "/root/face.jpg",
        "--result_dir", "/root/out",
        "--preprocess", "full",     # keep full photo, animate head within frame
        "--enhancer", "gfpgan",     # HD face restoration
        "--size", "512",
        "--pose_style", "0",
        "--expression_scale", "1.0",
        # NOTE: deliberately NO --still flag, so the head actually moves.
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    print(proc.stdout[-3000:])
    if proc.returncode != 0:
        tail = proc.stderr[-4000:]
        print("STDERR:\n" + tail)
        raise RuntimeError(f"SadTalker failed (rc={proc.returncode}):\n{tail}")

    mp4s = glob.glob("/root/out/**/*.mp4", recursive=True)
    if not mp4s:
        raise RuntimeError("SadTalker produced no mp4 output")
    # Prefer the gfpgan-enhanced render.
    enhanced = [m for m in mp4s if "enhanced" in m.lower()]
    out_path = (enhanced or mp4s)[0]
    print(f"📦 Selected output: {out_path}")
    with open(out_path, "rb") as f:
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
    print(f"📤 Uploading {len(img)} bytes image + {len(aud)} bytes audio to Modal A10G...")
    result = talking_head.remote(img, aud)
    with open(out, "wb") as f:
        f.write(result)
    print(f"✅ HD talking head WITH head motion written: {out} ({len(result)} bytes)")

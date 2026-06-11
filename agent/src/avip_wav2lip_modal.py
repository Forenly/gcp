"""
AVIP Talking Avatar — REAL HD lip-sync on Modal A10G GPU (Wav2Lip + GFPGAN).

Replaces the old OpenCV mouth-stretch hack (~/scratch/animate_avatar_dynamic.py)
which warped a static photo and looked distorted. Pipeline on a serverless
NVIDIA A10G GPU:
  1. Wav2Lip GAN  — genuine mouth movement locked to the audio waveform.
  2. GFPGAN v1.4  — restores facial detail frame-by-frame so the mouth/face is
                    crisp HD instead of the soft 96px Wav2Lip patch.

Inputs : bahadir.jpg (still photo) + tts_narration.wav (TTS voice track)
Output : talking_avatar.mp4 (HD lip-synced talking head, narrates the demos)

Run:  modal run avip_wav2lip_modal.py
"""
import modal

# Checkpoints are baked into the image at build time (cached across runs).
WAV2LIP_GAN_URLS = [
    "https://huggingface.co/Non-playing-Character/Wave2lip/resolve/main/wav2lip_gan.pth",
    "https://huggingface.co/camenduru/Wav2Lip/resolve/main/checkpoints/wav2lip_gan.pth",
    "https://huggingface.co/spaces/manavisrani07/gradio-lipsync-wav2lip/resolve/main/checkpoints/wav2lip_gan.pth",
]
# justinjohn0306 fork uses batch_face RetinaFace (mobilenet) instead of s3fd.
MOBILENET_URLS = [
    "https://huggingface.co/spaces/manavisrani07/gradio-lipsync-wav2lip/resolve/main/checkpoints/mobilenet.pth",
    "https://github.com/justinjohn0306/Wav2Lip/releases/download/models/mobilenet.pth",
]
_wget_mobilenet = " || ".join(
    f"wget -q '{u}' -O /root/Wav2Lip/checkpoints/mobilenet.pth" for u in MOBILENET_URLS
)

_wget_gan = " || ".join(
    f"wget -q '{u}' -O /root/Wav2Lip/checkpoints/wav2lip_gan.pth" for u in WAV2LIP_GAN_URLS
)

GFPGAN_URL = "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth"

image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("ffmpeg", "git", "wget", "libgl1", "libglib2.0-0")
    .pip_install(
        # pinned: torch 2.12 pulls a cuda-toolkit metapackage that breaks basicsr's build
        "torch==2.5.1",
        "torchvision==0.20.1",
        "numpy<2",
        "opencv-python-headless",
        "librosa==0.10.2",
        "scipy",
        "tqdm",
        "numba",
        "soundfile",
        "batch_face",
        "cython",
    )
    # HD face restoration. basicsr is an sdist whose isolated build resolves a
    # conflicting CUDA metapackage — install with --no-build-isolation so it
    # reuses the torch/numpy already in the image instead of fetching eggs.
    .run_commands(
        "pip install --no-build-isolation basicsr facexlib gfpgan realesrgan",
    )
    .run_commands(
        "cd /root && git clone --depth 1 https://github.com/justinjohn0306/Wav2Lip.git",
        "mkdir -p /root/Wav2Lip/checkpoints /root/gfpgan_models",
        # wav2lip_gan.pth (mirror fallback chain) — must be ~436MB
        _wget_gan,
        # RetinaFace mobilenet face detector (~1.7MB)
        _wget_mobilenet,
        # GFPGAN v1.4 restoration model (~333MB)
        f"wget -q '{GFPGAN_URL}' -O /root/gfpgan_models/GFPGANv1.4.pth",
        # sanity: fail the build early if a checkpoint did not download
        "test $(stat -c%s /root/Wav2Lip/checkpoints/wav2lip_gan.pth) -gt 400000000",
        "test $(stat -c%s /root/Wav2Lip/checkpoints/mobilenet.pth) -gt 1000000",
        "test $(stat -c%s /root/gfpgan_models/GFPGANv1.4.pth) -gt 100000000",
        # Make audio.py librosa-version-agnostic (mel sr/n_fft are keyword-only in librosa>=0.10)
        r"sed -i 's/librosa\.filters\.mel(hp\.sample_rate, hp\.n_fft,/librosa.filters.mel(sr=hp.sample_rate, n_fft=hp.n_fft,/' /root/Wav2Lip/audio.py",
        # torchvision>=0.17 removed transforms.functional_tensor which basicsr imports.
        # Drop a shim module that re-exports the one symbol basicsr needs.
        "python -c \"import torchvision.transforms.functional as F, os; open(os.path.join(os.path.dirname(F.__file__), 'functional_tensor.py'), 'w').write('from torchvision.transforms.functional import rgb_to_grayscale\\n')\"",
    )
)

app = modal.App("avip-wav2lip-avatar", image=image)


@app.function(gpu="A10G", timeout=900)
def lipsync(image_bytes: bytes, audio_bytes: bytes) -> bytes:
    import os
    import subprocess

    os.chdir("/root/Wav2Lip")
    with open("face.jpg", "wb") as f:
        f.write(image_bytes)
    with open("audio.wav", "wb") as f:
        f.write(audio_bytes)

    print("🎬 [1/3] Running Wav2Lip lip-sync on A10G GPU...")
    cmd = [
        "python", "inference.py",
        "--checkpoint_path", "checkpoints/wav2lip_gan.pth",
        "--face", "face.jpg",
        "--audio", "audio.wav",
        "--outfile", "/root/Wav2Lip/raw.mp4",
        "--static", "True",       # single still image
        "--fps", "25",
        "--pads", "0", "15", "0", "0",  # extra chin padding so the mouth isn't clipped
        "--nosmooth",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    print(proc.stdout[-2000:])
    if proc.returncode != 0:
        tail = proc.stderr[-3000:]
        print("STDERR:\n" + tail)
        raise RuntimeError(f"Wav2Lip inference failed (rc={proc.returncode}):\n{tail}")

    out = _enhance_gfpgan("/root/Wav2Lip/raw.mp4", "audio.wav")
    with open(out, "rb") as f:
        return f.read()


def _enhance_gfpgan(raw_video: str, audio_path: str) -> str:
    """Frame-by-frame GFPGAN restoration → crisp HD face, then re-mux audio."""
    import glob
    import os
    import subprocess

    import cv2
    from gfpgan import GFPGANer

    frames_in = "/root/frames_in"
    frames_out = "/root/frames_out"
    os.makedirs(frames_in, exist_ok=True)
    os.makedirs(frames_out, exist_ok=True)

    print("🖼️  [2/3] Extracting frames for HD restoration...")
    subprocess.run(
        ["ffmpeg", "-y", "-i", raw_video, "-qscale:v", "2", f"{frames_in}/f_%05d.jpg"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
    )

    print("✨ [2/3] Restoring faces with GFPGAN v1.4 (upscale x2)...")
    restorer = GFPGANer(
        model_path="/root/gfpgan_models/GFPGANv1.4.pth",
        upscale=2,
        arch="clean",
        channel_multiplier=2,
        bg_upsampler=None,
    )
    frame_files = sorted(glob.glob(f"{frames_in}/f_*.jpg"))
    for i, fp in enumerate(frame_files):
        img = cv2.imread(fp)
        _, _, restored = restorer.enhance(
            img, has_aligned=False, only_center_face=True, paste_back=True
        )
        cv2.imwrite(os.path.join(frames_out, os.path.basename(fp)), restored)
        if i % 100 == 0:
            print(f"   ...{i}/{len(frame_files)} frames")

    print("🎞️  [3/3] Re-assembling HD video with audio...")
    final = "/root/Wav2Lip/result.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-framerate", "25", "-i", f"{frames_out}/f_%05d.jpg",
            "-i", audio_path,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17",
            "-c:a", "aac", "-b:a", "192k", "-shortest", final,
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
    )
    return final


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
    result = lipsync.remote(img, aud)
    with open(out, "wb") as f:
        f.write(result)
    print(f"✅ Real lip-synced talking avatar written: {out} ({len(result)} bytes)")

"""Build-time: bake the SeedVR2 weights into the image (see Dockerfile).

Runs during the image build so the worker ships with its weights and needs NO
network volume at runtime — letting you deploy in any datacenter that has GPU
availability (RunPod network volumes exist in only a few DCs, which often don't
overlap with GPU availability).

We download the files DIRECTLY from HuggingFace rather than importing SeedVR2's
own downloader: that downloader pulls in the model registry → the DiT/VAE torch
model classes (and their optional attention backends), which can fail to import at
build time. Downloading the plain files avoids that whole chain. The repo id and
filenames mirror `src/utils/model_registry.py` of the pinned SeedVR2 commit, and
the destination matches what the runtime pipeline reads — so at runtime the
handler's download_weight finds these files, validates them once, and skips the
multi-GB download.

Baked set: 7B fp16 DiT + the shared VAE (best-quality image upscaling). Add more
filenames to BAKE_FILES to bake additional variants (bigger image). Any model NOT
baked still works — it just downloads at runtime on first use (slow, and without a
volume it won't persist across cold starts).
"""

import os

from huggingface_hub import hf_hub_download

# Mirrors src/utils/model_registry.py: the fp16 7B DiT + DEFAULT_VAE both live in
# the numz/SeedVR2_comfyUI repo.
REPO = "numz/SeedVR2_comfyUI"
BAKE_FILES = [
    "seedvr2_ema_7b_fp16.safetensors",  # DiT (7B fp16) — the node's default model
    "ema_vae_fp16.safetensors",         # DEFAULT_VAE — shared across all DiT models
]

model_dir = os.environ["SEEDVR2_MODEL_DIR"]
os.makedirs(model_dir, exist_ok=True)

for filename in BAKE_FILES:
    path = hf_hub_download(repo_id=REPO, filename=filename, local_dir=model_dir)
    size_gb = os.path.getsize(path) / (1024 ** 3)
    print(f"baked {filename} -> {path} ({size_gb:.2f} GB)", flush=True)

print("baked weights in", model_dir, "->", sorted(os.listdir(model_dir)), flush=True)

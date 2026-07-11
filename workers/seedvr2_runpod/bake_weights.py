"""Build-time: bake the SeedVR2 weights into the image (see Dockerfile).

Runs during the image build so the worker ships with its weights and needs NO
network volume at runtime — letting you deploy in any datacenter that has GPU
availability (RunPod network volumes exist in only a few DCs, which often don't
overlap with GPU availability).

Uses SeedVR2's own download_weight so the on-disk layout + validation cache match
exactly what the runtime pipeline expects; at runtime the handler re-calls
download_weight, finds these files already valid, and skips the download.

Baked set: 7B fp16 DiT + the shared VAE (best-quality image upscaling). Add more
filenames to BAKE_MODELS to bake additional variants (bigger image). Any model NOT
baked still works — it just downloads at runtime on first use (slow, and without a
volume it won't persist across cold starts).
"""

import os
import sys

SEEDVR2_DIR = os.environ.get("SEEDVR2_DIR", "/app/SeedVR2")
sys.path.insert(0, SEEDVR2_DIR)

from src.utils.downloads import download_weight       # noqa: E402
from src.utils.model_registry import DEFAULT_VAE      # noqa: E402
from src.utils.debug import Debug                     # noqa: E402

BAKE_MODELS = ["seedvr2_ema_7b_fp16.safetensors"]

model_dir = os.environ["SEEDVR2_MODEL_DIR"]
os.makedirs(model_dir, exist_ok=True)
debug = Debug(enabled=True)

for dit_model in BAKE_MODELS:
    if not download_weight(dit_model=dit_model, vae_model=DEFAULT_VAE,
                           model_dir=model_dir, debug=debug):
        raise SystemExit(f"bake_weights: failed to download {dit_model}")

print("baked weights in", model_dir, "->", sorted(os.listdir(model_dir)))

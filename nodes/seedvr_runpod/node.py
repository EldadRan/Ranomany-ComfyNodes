"""
SeedVR2 image upscaler on RunPod serverless — ComfyUI node.

  RanomanySeedVR2Upscale → your RunPod endpoint running workers/seedvr2_runpod/

The heavy lifting (SeedVR2 diffusion upscale, numz/ComfyUI-SeedVR2_VideoUpscaler)
happens on the RunPod GPU worker; this node just ships the image over the shared
runpod_common transport and decodes the result. Nothing runs locally.

Config: RUNPOD_API_KEY + RUNPOD_ENDPOINT_ID (env / .env / node inputs).
See runpod_common.resolve_config.
"""

import logging
import random

# Shared RunPod client. __init__.py registers it in sys.modules before the node loop;
# the fallback bootstraps it when this file is imported standalone (e.g. tests).
try:
    import ranomany_runpod_common as rp
except ImportError:  # pragma: no cover - standalone import path
    import importlib.util
    import os
    _p = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "runpod_common", "client.py"))
    _spec = importlib.util.spec_from_file_location("ranomany_runpod_common", _p)
    rp = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(rp)

log = logging.getLogger("SeedVR2RunPod")

CATEGORY = "Ranomany/RunPod"

# DiT checkpoints known to the worker's pinned SeedVR2 build (src/utils/model_registry.py).
# The worker's image bakes in 7B fp16 (the default below); it runs with no download.
# Any other choice downloads on the worker's first use of it — slow, and without a
# network volume it re-downloads on each cold start.
_DIT_MODELS = [
    "seedvr2_ema_7b_fp16.safetensors",
    "seedvr2_ema_7b_sharp_fp16.safetensors",
    "seedvr2_ema_7b_fp8_e4m3fn_mixed_block35_fp16.safetensors",
    "seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors",
    "seedvr2_ema_7b-Q4_K_M.gguf",
    "seedvr2_ema_7b_sharp-Q4_K_M.gguf",
    "seedvr2_ema_3b_fp16.safetensors",
    "seedvr2_ema_3b_fp8_e4m3fn.safetensors",
    "seedvr2_ema_3b-Q8_0.gguf",
    "seedvr2_ema_3b-Q4_K_M.gguf",
]
_DEFAULT_MODEL = _DIT_MODELS[0]  # seedvr2_ema_7b_fp16 — baked into the worker image

_COLOR_CORRECTIONS = ["wavelet", "lab", "wavelet_adaptive", "hsv", "adain", "none"]

_CONFIG_HELP = (
    "No RunPod config found. Pass api_key / endpoint_id via the node inputs, set "
    "RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID in your environment, or add them to a "
    ".env file in your ComfyUI root."
)


class RanomanySeedVR2Upscale:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {"tooltip": "Image to upscale (first frame of a batch is used)."}),
            },
            "optional": {
                "model": (_DIT_MODELS, {"default": _DEFAULT_MODEL,
                                        "tooltip": "SeedVR2 DiT checkpoint. The default (7B fp16) is baked "
                                                   "into the worker; other choices download on first use."}),
                "resolution": ("INT", {"default": 1080, "min": 256, "max": 7680, "step": 8,
                                       "tooltip": "Target short-side resolution of the result."}),
                "max_resolution": ("INT", {"default": 0, "min": 0, "max": 15360, "step": 8,
                                           "tooltip": "Cap on the longest edge. 0 = unlimited."}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647, "step": 1,
                                 "tooltip": "Random seed. -1 = random each run (the used seed is returned)."}),
                "color_correction": (_COLOR_CORRECTIONS, {"default": "wavelet"}),
                "endpoint_id": ("STRING", {
                    "default": "",
                    "tooltip": "Leave blank to use RUNPOD_ENDPOINT_ID env var or .env file.",
                }),
                "api_key": ("STRING", {
                    "default": "", "password": True,
                    "tooltip": "Leave blank to use RUNPOD_API_KEY env var or .env file.",
                }),
                "max_wait": ("INT", {"default": 600, "min": 60, "max": 3600, "step": 30,
                                     "tooltip": "Give a cold endpoint time to start and download weights."}),
                "poll_interval": ("INT", {"default": 5, "min": 1, "max": 30, "step": 1}),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "STRING")
    RETURN_NAMES = ("image", "seed", "key_status")
    FUNCTION     = "upscale"
    CATEGORY     = CATEGORY
    OUTPUT_NODE  = False

    def upscale(self, image, model=_DEFAULT_MODEL, resolution=1080, max_resolution=0,
                seed=-1, color_correction="wavelet",
                endpoint_id="", api_key="", max_wait=600, poll_interval=5):
        key, endpoint, key_status = rp.resolve_config(api_key, endpoint_id)
        if not key or not endpoint:
            raise EnvironmentError(_CONFIG_HELP)

        # Send a concrete seed so the run is reproducible from the returned value.
        if seed < 0:
            seed = random.randint(0, 2147483647)

        payload = {
            "mode": "upscale",
            "image": rp.image_to_b64(image),
            "image_mime": "image/png",
            "model": model,
            "resolution": int(resolution),
            "max_resolution": int(max_resolution),
            "seed": int(seed),
            "color_correction": color_correction,
        }

        log.info(f"[SeedVR2Upscale] model={model} resolution={resolution} "
                 f"max_resolution={max_resolution} seed={seed} cc={color_correction}")
        output = rp.run(endpoint, key, payload, max_wait, poll_interval,
                        label="SeedVR2Upscale")
        result, out_seed = rp.result_to_image(output, label="SeedVR2Upscale")
        return (result, out_seed, key_status)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

NODE_CLASS_MAPPINGS = {
    "RanomanySeedVR2Upscale": RanomanySeedVR2Upscale,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RanomanySeedVR2Upscale": "SeedVR2 Upscale (RunPod)",
}

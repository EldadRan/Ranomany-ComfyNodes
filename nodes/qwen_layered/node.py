"""
Qwen Image Layered on fal.ai — ComfyUI node.

  QwenImageLayered → fal-ai/qwen-image-layered

Decomposes a single input image into multiple RGBA layers for compositing
workflows. Reuses the shared fal_common client (auth, submit/poll, media
data-URIs) and returns a ComfyUI IMAGE batch (one frame per layer) plus a
matching MASK batch carrying each layer's alpha (1 = transparent).

Key: FAL_KEY (env / .env / api_key input). See fal_common.resolve_key.
"""

import logging

# Shared fal client. __init__.py registers it in sys.modules before the node loop;
# the fallback bootstraps it when this file is imported standalone (e.g. tests).
try:
    import ranomany_fal_common as fal
except ImportError:  # pragma: no cover - standalone import path
    import importlib.util
    import os
    _p = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "fal_common", "client.py"))
    _spec = importlib.util.spec_from_file_location("ranomany_fal_common", _p)
    fal = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(fal)

log = logging.getLogger("QwenImageLayered")

CATEGORY = "Ranomany/fal.ai"

_MODEL = "fal-ai/qwen-image-layered"

_KEY_HELP = (
    "No FAL_KEY found. Pass it via the api_key input, set FAL_KEY in your "
    "environment, or add FAL_KEY=... to a .env file in your ComfyUI root."
)


def _resolve_or_raise(api_key: str) -> tuple:
    key, status = fal.resolve_key(api_key)
    if not key:
        raise EnvironmentError(_KEY_HELP)
    return key, status


class QwenImageLayered:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {"tooltip": "Image to decompose into layers."}),
            },
            "optional": {
                "prompt": ("STRING", {"multiline": True, "default": "",
                                      "placeholder": "Optional visual description of the input image."}),
                "num_layers": ("INT", {"default": 4, "min": 1, "max": 16, "step": 1,
                                       "tooltip": "Number of RGBA layers to generate."}),
                "num_inference_steps": ("INT", {"default": 28, "min": 1, "max": 100, "step": 1}),
                "guidance_scale": ("FLOAT", {"default": 5.0, "min": 0.0, "max": 20.0, "step": 0.1,
                                             "tooltip": "Strength of prompt adherence."}),
                "negative_prompt": ("STRING", {"default": "", "multiline": False,
                                               "tooltip": "Undesired elements to exclude."}),
                "output_format": (["png", "webp"], {"default": "png"}),
                "acceleration": (["none", "regular", "high"], {"default": "regular",
                                 "tooltip": "Higher acceleration is faster but may reduce quality."}),
                "enable_safety_checker": (["true", "false"], {"default": "true"}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647, "step": 1,
                                 "tooltip": "Random seed. -1 = random each run."}),
                "api_key": ("STRING", {
                    "default": "", "password": True,
                    "tooltip": "Leave blank to use FAL_KEY env var or .env file.",
                }),
                "max_wait": ("INT", {"default": 300, "min": 30, "max": 900, "step": 30}),
                "poll_interval": ("INT", {"default": 3, "min": 1, "max": 30, "step": 1}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "INT", "STRING")
    RETURN_NAMES = ("layers", "masks", "seed", "key_status")
    FUNCTION     = "generate"
    CATEGORY     = CATEGORY
    OUTPUT_NODE  = False

    def generate(self, image, prompt="", num_layers=4, num_inference_steps=28,
                 guidance_scale=5.0, negative_prompt="", output_format="png",
                 acceleration="regular", enable_safety_checker="true", seed=-1,
                 api_key="", max_wait=300, poll_interval=3):
        key, key_status = _resolve_or_raise(api_key)

        payload = {
            "image_url": fal.image_to_data_uri(image),
            "num_layers": int(num_layers),
            "num_inference_steps": int(num_inference_steps),
            "guidance_scale": float(guidance_scale),
            "output_format": output_format,
            "acceleration": acceleration,
            "enable_safety_checker": enable_safety_checker == "true",
        }
        if prompt.strip():
            payload["prompt"] = prompt.strip()
        if negative_prompt.strip():
            payload["negative_prompt"] = negative_prompt.strip()
        if seed >= 0:
            payload["seed"] = int(seed)

        log.info(f"[QwenImageLayered] num_layers={num_layers} steps={num_inference_steps} "
                 f"accel={acceleration}")
        result = fal.run(_MODEL, payload, key, max_wait, poll_interval, label="QwenImageLayered")
        layers, masks, out_seed = fal.result_to_images_rgba(result)
        return (layers, masks, out_seed, key_status)


NODE_CLASS_MAPPINGS = {
    "QwenImageLayered": QwenImageLayered,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QwenImageLayered": "Qwen Image Layered (fal)",
}

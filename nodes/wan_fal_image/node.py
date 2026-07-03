"""
Wan 2.6 image models on fal.ai — text-to-image and image-to-image ComfyUI nodes.

  WanFalTextToImage  → wan/v2.6/text-to-image
  WanFalImageToImage → wan/v2.6/image-to-image

Both reuse the shared fal_common client (auth, submit/poll, media data-URIs) and
output a standard ComfyUI IMAGE batch — no wheel re-invention.

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

log = logging.getLogger("WanFalImage")

CATEGORY = "Ranomany/fal.ai"

_T2I_MODEL = "wan/v2.6/text-to-image"
_I2I_MODEL = "wan/v2.6/image-to-image"

_IMAGE_SIZES = ["square_hd", "square", "portrait_4_3", "portrait_16_9",
                "landscape_4_3", "landscape_16_9"]

_KEY_HELP = (
    "No FAL_KEY found. Pass it via the api_key input, set FAL_KEY in your "
    "environment, or add FAL_KEY=... to a .env file in your ComfyUI root."
)


def _prompt_field(placeholder: str):
    return ("STRING", {"multiline": True, "default": "", "placeholder": placeholder})


def _common_optional() -> dict:
    """api_key + polling knobs shared by every fal node (image gen is quick)."""
    return {
        "api_key": ("STRING", {
            "default": "", "password": True,
            "tooltip": "Leave blank to use FAL_KEY env var or .env file.",
        }),
        "max_wait": ("INT", {"default": 300, "min": 30, "max": 900, "step": 30}),
        "poll_interval": ("INT", {"default": 3, "min": 1, "max": 30, "step": 1}),
    }


def _resolve_or_raise(api_key: str) -> tuple:
    key, status = fal.resolve_key(api_key)
    if not key:
        raise EnvironmentError(_KEY_HELP)
    return key, status


# ---------------------------------------------------------------------------
# Text → image
# ---------------------------------------------------------------------------

class WanFalTextToImage:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": _prompt_field("Describe the image (max 2000 chars). English or Chinese."),
            },
            "optional": {
                "reference_image": ("IMAGE", {"tooltip": "Optional reference for style guidance."}),
                "image_size": (_IMAGE_SIZES, {"default": "square_hd"}),
                "max_images": ("INT", {"default": 1, "min": 1, "max": 5, "step": 1,
                                       "tooltip": "Up to 5 images per request (actual count may vary)."}),
                "negative_prompt": ("STRING", {"default": "", "multiline": False,
                                               "tooltip": "Content to avoid (max 500 chars)."}),
                "enable_safety_checker": (["true", "false"], {"default": "true"}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647, "step": 1,
                                 "tooltip": "Random seed. -1 = random each run."}),
                **_common_optional(),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "STRING")
    RETURN_NAMES = ("images", "seed", "key_status")
    FUNCTION     = "generate"
    CATEGORY     = CATEGORY
    OUTPUT_NODE  = False

    def generate(self, prompt, reference_image=None, image_size="square_hd", max_images=1,
                 negative_prompt="", enable_safety_checker="true", seed=-1,
                 api_key="", max_wait=300, poll_interval=3):
        if not prompt.strip():
            raise ValueError("WanFalTextToImage: prompt is required.")
        key, key_status = _resolve_or_raise(api_key)

        payload = {
            "prompt": prompt.strip(),
            "image_size": image_size,
            "max_images": int(max_images),
            "enable_safety_checker": enable_safety_checker == "true",
        }
        if reference_image is not None:
            payload["image_url"] = fal.image_to_data_uri(reference_image)
        if negative_prompt.strip():
            payload["negative_prompt"] = negative_prompt.strip()
        if seed >= 0:
            payload["seed"] = int(seed)

        log.info(f"[WanFalTextToImage] size={image_size} max_images={max_images} ref={reference_image is not None}")
        result = fal.run(_T2I_MODEL, payload, key, max_wait, poll_interval, label="WanFalTextToImage")
        images, out_seed = fal.result_to_images(result)
        return (images, out_seed, key_status)


# ---------------------------------------------------------------------------
# Image → image (1–3 references)
# ---------------------------------------------------------------------------

class WanFalImageToImage:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": _prompt_field("Describe the edit. Refer to inputs as 'image 1', 'image 2', 'image 3'."),
                "image_1": ("IMAGE", {"tooltip": "First reference image (required)."}),
            },
            "optional": {
                "image_2": ("IMAGE", {"tooltip": "Second reference image (optional)."}),
                "image_3": ("IMAGE", {"tooltip": "Third reference image (optional)."}),
                "image_size": (_IMAGE_SIZES, {"default": "square_hd"}),
                "num_images": ("INT", {"default": 1, "min": 1, "max": 4, "step": 1}),
                "negative_prompt": ("STRING", {"default": "", "multiline": False,
                                               "tooltip": "Content to avoid (max 500 chars)."}),
                "enable_prompt_expansion": (["true", "false"], {"default": "true"}),
                "enable_safety_checker": (["true", "false"], {"default": "true"}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647, "step": 1,
                                 "tooltip": "Random seed. -1 = random each run."}),
                **_common_optional(),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "STRING")
    RETURN_NAMES = ("images", "seed", "key_status")
    FUNCTION     = "generate"
    CATEGORY     = CATEGORY
    OUTPUT_NODE  = False

    def generate(self, prompt, image_1, image_2=None, image_3=None,
                 image_size="square_hd", num_images=1, negative_prompt="",
                 enable_prompt_expansion="true", enable_safety_checker="true", seed=-1,
                 api_key="", max_wait=300, poll_interval=3):
        if not prompt.strip():
            raise ValueError("WanFalImageToImage: prompt is required.")
        key, key_status = _resolve_or_raise(api_key)

        image_urls = [fal.image_to_data_uri(img) for img in (image_1, image_2, image_3)
                      if img is not None]

        payload = {
            "prompt": prompt.strip(),
            "image_urls": image_urls,
            "image_size": image_size,
            "num_images": int(num_images),
            "enable_prompt_expansion": enable_prompt_expansion == "true",
            "enable_safety_checker": enable_safety_checker == "true",
        }
        if negative_prompt.strip():
            payload["negative_prompt"] = negative_prompt.strip()
        if seed >= 0:
            payload["seed"] = int(seed)

        log.info(f"[WanFalImageToImage] refs={len(image_urls)} size={image_size} num_images={num_images}")
        result = fal.run(_I2I_MODEL, payload, key, max_wait, poll_interval, label="WanFalImageToImage")
        images, out_seed = fal.result_to_images(result)
        return (images, out_seed, key_status)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

NODE_CLASS_MAPPINGS = {
    "WanFalTextToImage":  WanFalTextToImage,
    "WanFalImageToImage": WanFalImageToImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WanFalTextToImage":  "Wan 2.6 Text to Image (fal)",
    "WanFalImageToImage": "Wan 2.6 Image to Image (fal)",
}

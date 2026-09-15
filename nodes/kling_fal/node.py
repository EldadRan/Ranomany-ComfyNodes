"""
Kling 3 image-to-video on fal.ai — one ComfyUI node over the fal queue REST API.

  KlingFalImageToVideo → fal-ai/kling-video/v3/standard/image-to-video   (tier="standard")
                       → fal-ai/kling-video/v3/pro/image-to-video        (tier="pro")
                       → fal-ai/kling-video/v3/4k/image-to-video         (tier="4k")

All three endpoints take the same input schema; they differ in output quality and price,
so a single node with a `tier` selector covers them. Start frame only (FF) or start + end
frame (FFLF). Aspect ratio follows the start image.

Only the basic controls are exposed — multi_prompt/shot_type (multi-shot) and elements
(character/object references, voice binding) are not.

Transport (auth, submit/poll, media→data-URI, download) lives in the shared
`fal_common` client. Returns a VIDEO — wire it to the Save Video node.

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

log = logging.getLogger("KlingFal")

VIDEO = "VIDEO"
CATEGORY = "Ranomany/fal.ai"

_MODELS = {
    "standard": "fal-ai/kling-video/v3/standard/image-to-video",
    "pro":      "fal-ai/kling-video/v3/pro/image-to-video",
    "4k":       "fal-ai/kling-video/v3/4k/image-to-video",
}

_MAX_PROMPT_CHARS = 2500
# Per-image limits the endpoint enforces (start and end frame alike).
_MIN_SIDE = 300
_MIN_ASPECT, _MAX_ASPECT = 0.40, 2.50

_KEY_HELP = (
    "No FAL_KEY found. Pass it via the api_key input, set FAL_KEY in your "
    "environment, or add FAL_KEY=... to a .env file in your ComfyUI root."
)


def _check_image(image, name: str):
    """Reject frames the endpoint would refuse, before paying for an upload."""
    h, w = int(image.shape[-3]), int(image.shape[-2])
    if w < _MIN_SIDE or h < _MIN_SIDE:
        raise ValueError(f"KlingFalImageToVideo: {name} must be at least "
                         f"{_MIN_SIDE}×{_MIN_SIDE}px — got {w}×{h}.")
    aspect = w / h
    if not _MIN_ASPECT <= aspect <= _MAX_ASPECT:
        raise ValueError(f"KlingFalImageToVideo: {name} aspect ratio (w/h) must be "
                         f"{_MIN_ASPECT:.2f}–{_MAX_ASPECT:.2f} — got {aspect:.2f} ({w}×{h}).")


def _check_length(text: str, name: str):
    if len(text) > _MAX_PROMPT_CHARS:
        raise ValueError(f"KlingFalImageToVideo: {name} is {len(text)} chars — "
                         f"max {_MAX_PROMPT_CHARS}.")


class KlingFalImageToVideo:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image":  ("IMAGE", {"tooltip": "Start frame. Output aspect ratio follows this image."}),
                "prompt": ("STRING", {"multiline": True, "default": "",
                                      "placeholder": "Describe the video (max 2500 chars)."}),
            },
            "optional": {
                "tier": (["standard", "pro", "4k"], {
                    "default": "pro",
                    "tooltip": "standard = cheapest ($0.084/s, $0.126/s with audio). "
                               "pro = higher quality ($0.112/s, $0.168/s with audio). "
                               "4k = native 4K ($0.42/s, audio included).",
                }),
                "end_image": ("IMAGE", {
                    "tooltip": "Optional end frame — generates a transition between start and end."}),
                # Combo values are strings — ComfyUI's frontend round-trips widget values as
                # strings, and the endpoint's enum is strings too.
                "duration": ([str(s) for s in range(3, 16)], {
                    "default": "5", "tooltip": "Seconds."}),
                "generate_audio": (["true", "false"], {
                    "default": "true",
                    "tooltip": "Native audio. Speech in Chinese/English; other languages are "
                               "translated to English. Raises the price on standard/pro."}),
                "negative_prompt": ("STRING", {
                    "default": "blur, distort, and low quality", "multiline": False,
                    "tooltip": "Content to avoid (max 2500 chars). Blank = fal's default."}),
                "cfg_scale": ("FLOAT", {
                    "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "How closely the model sticks to the prompt."}),
                "api_key": ("STRING", {
                    "default": "", "password": True,
                    "tooltip": "Leave blank to use FAL_KEY env var or .env file.",
                }),
                "max_wait": ("INT", {"default": 900, "min": 60, "max": 1800, "step": 30}),
                "poll_interval": ("INT", {"default": 15, "min": 5, "max": 60, "step": 5}),
            },
        }

    RETURN_TYPES = (VIDEO, "STRING")
    RETURN_NAMES = ("video", "key_status")
    FUNCTION     = "generate"
    CATEGORY     = CATEGORY
    OUTPUT_NODE  = False

    def generate(self, image, prompt, tier="pro", end_image=None, duration="5",
                 generate_audio="true", negative_prompt="blur, distort, and low quality",
                 cfg_scale=0.5, api_key="", max_wait=900, poll_interval=15):
        prompt = prompt.strip()
        negative_prompt = negative_prompt.strip()
        if not prompt:
            raise ValueError("KlingFalImageToVideo: prompt is required.")
        _check_length(prompt, "prompt")
        _check_length(negative_prompt, "negative_prompt")
        _check_image(image, "image")
        if end_image is not None:
            _check_image(end_image, "end_image")

        key, key_status = fal.resolve_key(api_key)
        if not key:
            raise EnvironmentError(_KEY_HELP)

        payload = {
            "prompt": prompt,
            "start_image_url": fal.image_to_data_uri(image),
            "duration": str(duration),
            "generate_audio": generate_audio == "true",
            "cfg_scale": float(cfg_scale),
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if end_image is not None:
            payload["end_image_url"] = fal.image_to_data_uri(end_image)

        log.info(f"[KlingFalImageToVideo] tier={tier} duration={duration}s audio={generate_audio} "
                 f"cfg={cfg_scale} end_image={end_image is not None}")
        result = fal.run(_MODELS[tier], payload, key, max_wait, poll_interval,
                         label="KlingFalImageToVideo")
        video, _seed = fal.result_to_video(result)
        return (video, key_status)


NODE_CLASS_MAPPINGS = {
    "KlingFalImageToVideo": KlingFalImageToVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "KlingFalImageToVideo": "Kling 3 Image to Video (fal)",
}

"""
Kling O1 (standard) image-to-video on fal.ai — one ComfyUI node over the fal queue REST API.

  KlingFalImageToVideo → fal-ai/kling-video/o1/standard/image-to-video

Start frame + prompt, optional end frame, duration 3–10s. The endpoint takes no seed,
resolution, fps or audio options and returns only a video.

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

_MODEL = "fal-ai/kling-video/o1/standard/image-to-video"

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


class KlingFalImageToVideo:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image":  ("IMAGE", {"tooltip": "Start frame (referenced as @Image1 in the prompt)."}),
                "prompt": ("STRING", {"multiline": True, "default": "",
                                      "placeholder": "Describe the video (max 2500 chars). "
                                                     "@Image1 = start frame, @Image2 = end frame."}),
            },
            "optional": {
                "end_image": ("IMAGE", {
                    "tooltip": "Optional end frame (@Image2) — generates a transition between start and end."}),
                # Combo values are strings — ComfyUI's frontend round-trips widget values as
                # strings, and the endpoint's enum is strings too.
                "duration": (["3", "4", "5", "6", "7", "8", "9", "10"], {
                    "default": "5", "tooltip": "Seconds."}),
                "api_key": ("STRING", {
                    "default": "", "password": True,
                    "tooltip": "Leave blank to use FAL_KEY env var or .env file.",
                }),
                "max_wait": ("INT", {"default": 600, "min": 60, "max": 1800, "step": 30}),
                "poll_interval": ("INT", {"default": 15, "min": 5, "max": 60, "step": 5}),
            },
        }

    RETURN_TYPES = (VIDEO, "STRING")
    RETURN_NAMES = ("video", "key_status")
    FUNCTION     = "generate"
    CATEGORY     = CATEGORY
    OUTPUT_NODE  = False

    def generate(self, image, prompt, end_image=None, duration="5",
                 api_key="", max_wait=600, poll_interval=15):
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("KlingFalImageToVideo: prompt is required.")
        if len(prompt) > _MAX_PROMPT_CHARS:
            raise ValueError(f"KlingFalImageToVideo: prompt is {len(prompt)} chars — "
                             f"max {_MAX_PROMPT_CHARS}.")
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
        }
        if end_image is not None:
            payload["end_image_url"] = fal.image_to_data_uri(end_image)

        log.info(f"[KlingFalImageToVideo] duration={duration}s end_image={end_image is not None}")
        result = fal.run(_MODEL, payload, key, max_wait, poll_interval,
                         label="KlingFalImageToVideo")
        video, _seed = fal.result_to_video(result)
        return (video, key_status)


NODE_CLASS_MAPPINGS = {
    "KlingFalImageToVideo": KlingFalImageToVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "KlingFalImageToVideo": "Kling O1 Image to Video (fal)",
}

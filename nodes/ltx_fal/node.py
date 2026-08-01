"""
LTX-2.3 image-to-video on fal.ai — one ComfyUI node over the fal queue REST API.

  LtxFalImageToVideo → fal-ai/ltx-2.3/image-to-video        (model="quality")
                     → fal-ai/ltx-2.3/image-to-video/fast   (model="fast")

Both endpoints take the same input schema; they differ only in the durations they
accept (quality: 6/8/10s, fast: 6–20s, where >10s requires 25fps + 1080p), so a
single node with a `model` selector covers both.

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

log = logging.getLogger("LtxFal")

VIDEO = "VIDEO"
CATEGORY = "Ranomany/fal.ai"

_MODELS = {
    "quality": "fal-ai/ltx-2.3/image-to-video",
    "fast":    "fal-ai/ltx-2.3/image-to-video/fast",
}

# Durations each endpoint accepts. The fast model additionally restricts anything
# over 10s to 25 fps / 1080p.
_DURATIONS = {
    "quality": (6, 8, 10),
    "fast":    (6, 8, 10, 12, 14, 16, 18, 20),
}
_LONG_DURATION_FPS = 25
_LONG_DURATION_RESOLUTION = "1080p"

_KEY_HELP = (
    "No FAL_KEY found. Pass it via the api_key input, set FAL_KEY in your "
    "environment, or add FAL_KEY=... to a .env file in your ComfyUI root."
)


class LtxFalImageToVideo:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image":  ("IMAGE", {"tooltip": "Start frame."}),
                "prompt": ("STRING", {"multiline": True, "default": "",
                                      "placeholder": "Describe the video (max 5000 chars)."}),
            },
            "optional": {
                "model": (["quality", "fast"], {
                    "default": "quality",
                    "tooltip": "quality = ltx-2.3/image-to-video (6/8/10s). "
                               "fast = .../fast (6–20s, cheaper/quicker).",
                }),
                "end_image": ("IMAGE", {
                    "tooltip": "Optional end frame — generates a transition between start and end."}),
                # Combo values are strings — ComfyUI's frontend round-trips widget values as
                # strings, so int-valued lists fail validation. Cast in generate().
                "duration": (["6", "8", "10", "12", "14", "16", "18", "20"], {
                    "default": "6",
                    "tooltip": "Seconds. quality supports 6/8/10; fast supports 6–20, "
                               "but >10 requires fps=25 and resolution=1080p."}),
                "resolution": (["1080p", "1440p", "2160p"], {"default": "1080p"}),
                "aspect_ratio": (["auto", "16:9", "9:16"], {
                    "default": "auto", "tooltip": "'auto' follows the input image's ratio."}),
                "fps": (["24", "25", "48", "50"], {"default": "25"}),
                "generate_audio": (["true", "false"], {"default": "true"}),
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

    def generate(self, image, prompt, model="quality", end_image=None, duration="6",
                 resolution="1080p", aspect_ratio="auto", fps="25", generate_audio="true",
                 api_key="", max_wait=600, poll_interval=15):
        if not prompt.strip():
            raise ValueError("LtxFalImageToVideo: prompt is required.")

        duration, fps = int(duration), int(fps)
        allowed = _DURATIONS[model]
        if duration not in allowed:
            raise ValueError(
                f"LtxFalImageToVideo: model='{model}' supports durations "
                f"{', '.join(str(d) for d in allowed)}s — got {duration}s."
            )
        if duration > 10 and (fps != _LONG_DURATION_FPS or resolution != _LONG_DURATION_RESOLUTION):
            raise ValueError(
                f"LtxFalImageToVideo: durations over 10s require fps={_LONG_DURATION_FPS} "
                f"and resolution={_LONG_DURATION_RESOLUTION} — got fps={fps}, resolution={resolution}."
            )

        key, key_status = fal.resolve_key(api_key)
        if not key:
            raise EnvironmentError(_KEY_HELP)

        payload = {
            "prompt": prompt.strip(),
            "image_url": fal.image_to_data_uri(image),
            "duration": duration,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "fps": fps,
            "generate_audio": generate_audio == "true",
        }
        if end_image is not None:
            payload["end_image_url"] = fal.image_to_data_uri(end_image)

        log.info(f"[LtxFalImageToVideo] model={model} duration={duration}s resolution={resolution} "
                 f"fps={fps} ratio={aspect_ratio} end_image={end_image is not None}")
        result = fal.run(_MODELS[model], payload, key, max_wait, poll_interval,
                         label="LtxFalImageToVideo")
        video, _seed = fal.result_to_video(result)
        return (video, key_status)


NODE_CLASS_MAPPINGS = {
    "LtxFalImageToVideo": LtxFalImageToVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LtxFalImageToVideo": "LTX-2.3 Image to Video (fal)",
}

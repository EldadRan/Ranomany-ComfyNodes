"""
Wan 2.7 on fal.ai — three ComfyUI nodes over the fal queue REST API.

  WanFalImageToVideo      → fal-ai/wan/v2.7/image-to-video
  WanFalEditVideo         → fal-ai/wan/v2.7/edit-video
  WanFalReferenceToVideo  → fal-ai/wan/v2.7/reference-to-video

All transport (auth, submit/poll, media→data-URI, download) lives in the shared
`fal_common` client so future fal models reuse it. Each node just builds a top-level
payload dict and returns a VIDEO — wire it to the Save Video node.

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

log = logging.getLogger("WanFal")

VIDEO = "VIDEO"
CATEGORY = "Ranomany/fal.ai"

_T2V_MODEL = "fal-ai/wan/v2.7/text-to-video"
_I2V_MODEL = "fal-ai/wan/v2.7/image-to-video"
_EDIT_MODEL = "fal-ai/wan/v2.7/edit-video"
_R2V_MODEL = "fal-ai/wan/v2.7/reference-to-video"

_KEY_HELP = (
    "No FAL_KEY found. Pass it via the api_key input, set FAL_KEY in your "
    "environment, or add FAL_KEY=... to a .env file in your ComfyUI root."
)


def _prompt_field(placeholder: str):
    return ("STRING", {"multiline": True, "default": "", "placeholder": placeholder})


def _toggle():
    return ("BOOLEAN", {"default": True, "label_on": "use", "label_off": "skip",
                        "tooltip": "When off, this input is skipped even if something is wired to it."})


def _common_optional() -> dict:
    """api_key + polling knobs shared by every fal node."""
    return {
        "api_key": ("STRING", {
            "default": "", "password": True,
            "tooltip": "Leave blank to use FAL_KEY env var or .env file.",
        }),
        "max_wait": ("INT", {"default": 600, "min": 60, "max": 1800, "step": 30}),
        "poll_interval": ("INT", {"default": 15, "min": 5, "max": 60, "step": 5}),
    }


def _resolve_or_raise(api_key: str) -> tuple:
    key, status = fal.resolve_key(api_key)
    if not key:
        raise EnvironmentError(_KEY_HELP)
    return key, status


# ---------------------------------------------------------------------------
# Text → video
# ---------------------------------------------------------------------------

class WanFalTextToVideo:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": _prompt_field("Describe the video (max 5000 chars)."),
            },
            "optional": {
                "resolution": (["1080p", "720p"], {"default": "1080p"}),
                "aspect_ratio": (["16:9", "9:16", "1:1", "4:3", "3:4"], {"default": "16:9"}),
                "duration": ("INT", {"default": 5, "min": 2, "max": 15, "step": 1,
                                     "tooltip": "Output duration in seconds (2–15)."}),
                "negative_prompt": ("STRING", {"default": "", "multiline": False,
                                               "tooltip": "Content to exclude (max 500 chars)."}),
                "enable_prompt_expansion": (["true", "false"], {"default": "true"}),
                "enable_safety_checker":   (["true", "false"], {"default": "true"}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647, "step": 1,
                                 "tooltip": "Random seed. -1 = random each run."}),
                **_common_optional(),
            },
        }

    RETURN_TYPES = (VIDEO, "INT", "STRING")
    RETURN_NAMES = ("video", "seed", "key_status")
    FUNCTION     = "generate"
    CATEGORY     = CATEGORY
    OUTPUT_NODE  = False

    def generate(self, prompt, resolution="1080p", aspect_ratio="16:9", duration=5,
                 negative_prompt="", enable_prompt_expansion="true",
                 enable_safety_checker="true", seed=-1,
                 api_key="", max_wait=600, poll_interval=15):
        if not prompt.strip():
            raise ValueError("WanFalTextToVideo: prompt is required.")
        key, key_status = _resolve_or_raise(api_key)

        payload = {
            "prompt": prompt.strip(),
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "duration": int(duration),
            "enable_prompt_expansion": enable_prompt_expansion == "true",
            "enable_safety_checker": enable_safety_checker == "true",
        }
        if negative_prompt.strip():
            payload["negative_prompt"] = negative_prompt.strip()
        if seed >= 0:
            payload["seed"] = int(seed)

        log.info(f"[WanFalTextToVideo] resolution={resolution} ratio={aspect_ratio} duration={duration}s")
        result = fal.run(_T2V_MODEL, payload, key, max_wait, poll_interval, label="WanFalTextToVideo")
        video, out_seed = fal.result_to_video(result)
        return (video, out_seed, key_status)


# ---------------------------------------------------------------------------
# Image / first+last / continuation → video
# ---------------------------------------------------------------------------

class WanFalImageToVideo:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": _prompt_field("Describe the video (max 5000 chars)."),
            },
            "optional": {
                "image":       ("IMAGE", {"tooltip": "First frame. Required unless input_video is connected."}),
                "end_image":   ("IMAGE", {"tooltip": "Optional last frame (first+last-frame mode)."}),
                "input_video": (VIDEO, {"tooltip": "Continuation mode. Mutually exclusive with image."}),
                "resolution":  (["1080p", "720p"], {"default": "1080p"}),
                "duration":    ("INT", {"default": 5, "min": 2, "max": 15, "step": 1,
                                        "tooltip": "Output duration in seconds (2–15)."}),
                "negative_prompt": ("STRING", {"default": "", "multiline": False,
                                               "tooltip": "Content to exclude (max 500 chars)."}),
                "enable_prompt_expansion": (["true", "false"], {"default": "true"}),
                "enable_safety_checker":   (["true", "false"], {"default": "true"}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647, "step": 1,
                                 "tooltip": "Random seed. -1 = random each run."}),
                **_common_optional(),
            },
        }

    RETURN_TYPES = (VIDEO, "INT", "STRING")
    RETURN_NAMES = ("video", "seed", "key_status")
    FUNCTION     = "generate"
    CATEGORY     = CATEGORY
    OUTPUT_NODE  = False

    def generate(self, prompt, image=None, end_image=None, input_video=None,
                 resolution="1080p", duration=5, negative_prompt="",
                 enable_prompt_expansion="true", enable_safety_checker="true", seed=-1,
                 api_key="", max_wait=600, poll_interval=15):
        if image is None and input_video is None:
            raise ValueError("WanFalImageToVideo: connect an image (first frame) or an input_video.")
        key, key_status = _resolve_or_raise(api_key)

        payload = {
            "prompt": prompt.strip(),
            "resolution": resolution,
            "duration": int(duration),
            "enable_prompt_expansion": enable_prompt_expansion == "true",
            "enable_safety_checker": enable_safety_checker == "true",
        }
        if input_video is not None:
            payload["video_url"] = fal.video_to_data_uri(input_video)
            mode = "continuation"
        else:
            payload["image_url"] = fal.image_to_data_uri(image)
            mode = "i2v"
            if end_image is not None:
                payload["end_image_url"] = fal.image_to_data_uri(end_image)
                mode = "first+last"
        if negative_prompt.strip():
            payload["negative_prompt"] = negative_prompt.strip()
        if seed >= 0:
            payload["seed"] = int(seed)

        log.info(f"[WanFalImageToVideo] mode={mode} resolution={resolution} duration={duration}s")
        result = fal.run(_I2V_MODEL, payload, key, max_wait, poll_interval, label="WanFalImageToVideo")
        video, out_seed = fal.result_to_video(result)
        return (video, out_seed, key_status)


# ---------------------------------------------------------------------------
# Instruction-based video editing
# ---------------------------------------------------------------------------

class WanFalEditVideo:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": _prompt_field("Editing instruction or style transfer description."),
                "video":  (VIDEO, {"tooltip": "Source video (MP4/MOV, 2–10s)."}),
            },
            "optional": {
                "reference_image": ("IMAGE", {"tooltip": "Optional reference for style/subject."}),
                "resolution":  (["1080p", "720p"], {"default": "1080p"}),
                "aspect_ratio": (["auto", "16:9", "9:16", "1:1", "4:3", "3:4"], {
                    "default": "auto", "tooltip": "'auto' follows the input video's ratio."}),
                "duration": ("INT", {"default": 0, "min": 0, "max": 10, "step": 1,
                                     "tooltip": "0 = match input duration; 2–10 to set length."}),
                "audio_setting": (["auto", "origin"], {"default": "auto"}),
                "enable_safety_checker": (["true", "false"], {"default": "true"}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647, "step": 1,
                                 "tooltip": "Random seed. -1 = random each run."}),
                **_common_optional(),
            },
        }

    RETURN_TYPES = (VIDEO, "INT", "STRING")
    RETURN_NAMES = ("video", "seed", "key_status")
    FUNCTION     = "generate"
    CATEGORY     = CATEGORY
    OUTPUT_NODE  = False

    def generate(self, prompt, video, reference_image=None, resolution="1080p",
                 aspect_ratio="auto", duration=0, audio_setting="auto",
                 enable_safety_checker="true", seed=-1,
                 api_key="", max_wait=600, poll_interval=15):
        if not prompt.strip():
            raise ValueError("WanFalEditVideo: prompt (edit instruction) is required.")
        key, key_status = _resolve_or_raise(api_key)

        payload = {
            "prompt": prompt.strip(),
            "video_url": fal.video_to_data_uri(video),
            "resolution": resolution,
            "duration": int(duration),
            "audio_setting": audio_setting,
            "enable_safety_checker": enable_safety_checker == "true",
        }
        if reference_image is not None:
            payload["reference_image_url"] = fal.image_to_data_uri(reference_image)
        if aspect_ratio != "auto":
            payload["aspect_ratio"] = aspect_ratio
        if seed >= 0:
            payload["seed"] = int(seed)

        log.info(f"[WanFalEditVideo] resolution={resolution} duration={duration}s ratio={aspect_ratio}")
        result = fal.run(_EDIT_MODEL, payload, key, max_wait, poll_interval, label="WanFalEditVideo")
        out_video, out_seed = fal.result_to_video(result)
        return (out_video, out_seed, key_status)


# ---------------------------------------------------------------------------
# Reference (multi-subject) → video
# ---------------------------------------------------------------------------

class WanFalReferenceToVideo:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": _prompt_field("Describe the video (max 5000 chars)."),
            },
            "optional": {
                "reference_image_1": ("IMAGE",),
                "use_reference_image_1": _toggle(),
                "reference_image_2": ("IMAGE",),
                "use_reference_image_2": _toggle(),
                "reference_image_3": ("IMAGE",),
                "use_reference_image_3": _toggle(),
                "reference_image_4": ("IMAGE",),
                "use_reference_image_4": _toggle(),
                "reference_video_1": (VIDEO,),
                "use_reference_video_1": _toggle(),
                "reference_video_2": (VIDEO,),
                "use_reference_video_2": _toggle(),
                "negative_prompt": ("STRING", {"default": "", "multiline": False,
                                               "tooltip": "Content to exclude (max 500 chars)."}),
                "aspect_ratio": (["16:9", "9:16", "1:1", "4:3", "3:4"], {"default": "16:9"}),
                "resolution": (["1080p", "720p"], {"default": "1080p"}),
                "duration": ("INT", {"default": 5, "min": 2, "max": 10, "step": 1,
                                     "tooltip": "Output duration in seconds (2–10)."}),
                "multi_shots": (["false", "true"], {"default": "false",
                                "tooltip": "Intelligent multi-shot segmentation."}),
                "enable_safety_checker": (["true", "false"], {"default": "true"}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647, "step": 1,
                                 "tooltip": "Random seed. -1 = random each run."}),
                **_common_optional(),
            },
        }

    RETURN_TYPES = (VIDEO, "INT", "STRING")
    RETURN_NAMES = ("video", "seed", "key_status")
    FUNCTION     = "generate"
    CATEGORY     = CATEGORY
    OUTPUT_NODE  = False

    def generate(self, prompt,
                 reference_image_1=None, reference_image_2=None, reference_image_3=None,
                 reference_image_4=None, reference_video_1=None, reference_video_2=None,
                 use_reference_image_1=True, use_reference_image_2=True, use_reference_image_3=True,
                 use_reference_image_4=True, use_reference_video_1=True, use_reference_video_2=True,
                 negative_prompt="", aspect_ratio="16:9", resolution="1080p",
                 duration=5, multi_shots="false", enable_safety_checker="true", seed=-1,
                 api_key="", max_wait=600, poll_interval=15):
        if not prompt.strip():
            raise ValueError("WanFalReferenceToVideo: prompt is required.")
        key, key_status = _resolve_or_raise(api_key)

        # Every reference is gated by its use_* toggle.
        images = [
            (reference_image_1, use_reference_image_1),
            (reference_image_2, use_reference_image_2),
            (reference_image_3, use_reference_image_3),
            (reference_image_4, use_reference_image_4),
        ]
        videos = [
            (reference_video_1, use_reference_video_1),
            (reference_video_2, use_reference_video_2),
        ]
        image_urls = [fal.image_to_data_uri(img) for img, on in images if img is not None and on]
        video_urls = [fal.video_to_data_uri(v) for v, on in videos if v is not None and on]
        if not image_urls and not video_urls:
            raise ValueError("WanFalReferenceToVideo: connect (and enable) at least one reference image or video.")

        payload = {
            "prompt": prompt.strip(),
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "duration": int(duration),
            "multi_shots": multi_shots == "true",
            "enable_safety_checker": enable_safety_checker == "true",
        }
        if image_urls:
            payload["reference_image_urls"] = image_urls
        if video_urls:
            payload["reference_video_urls"] = video_urls
        if negative_prompt.strip():
            payload["negative_prompt"] = negative_prompt.strip()
        if seed >= 0:
            payload["seed"] = int(seed)

        log.info(f"[WanFalReferenceToVideo] images={len(image_urls)} videos={len(video_urls)} "
                 f"resolution={resolution} duration={duration}s")
        result = fal.run(_R2V_MODEL, payload, key, max_wait, poll_interval, label="WanFalReferenceToVideo")
        video, out_seed = fal.result_to_video(result)
        return (video, out_seed, key_status)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

NODE_CLASS_MAPPINGS = {
    "WanFalTextToVideo":      WanFalTextToVideo,
    "WanFalImageToVideo":     WanFalImageToVideo,
    "WanFalEditVideo":        WanFalEditVideo,
    "WanFalReferenceToVideo": WanFalReferenceToVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WanFalTextToVideo":      "Wan 2.7 Text to Video (fal)",
    "WanFalImageToVideo":     "Wan 2.7 Image to Video (fal)",
    "WanFalEditVideo":        "Wan 2.7 Edit Video (fal)",
    "WanFalReferenceToVideo": "Wan 2.7 Reference to Video (fal)",
}

"""
WanVideo / WanVideoEdit — ComfyUI nodes for Wan 2.7 video generation and editing.

Calls the Alibaba Cloud Model Studio (DashScope) API directly via raw HTTP.

API key resolution order:
  1. Value passed via the `api_key` input
  2. DASHSCOPE_API_KEY environment variable
  3. .env file — searched in the node dir, custom_nodes/, and ComfyUI root

WanVideo supports:
  - Text-to-video (no image connected)          → model: wan2.7-t2v
  - Image-to-video (first_frame connected)      → model: wan2.7-i2v-2026-04-25
  - First+last frame / r2v (both connected)     → model: wan2.7-i2v-2026-04-25
  - Video continuation (first_clip connected)   → model: wan2.7-i2v-2026-04-25

WanVideoEdit supports:
  - Instruction-based video editing             → model: wan2.7-videoedit
  - With optional reference images for style/character transfer

Both output a VIDEO value — wire to Save Video node.

Endpoint (Beijing):   https://dashscope.aliyuncs.com/api/v1
Endpoint (Singapore): https://{workspace_id}.ap-southeast-1.maas.aliyuncs.com/api/v1
"""

import base64
import io
import json
import logging
import os
import tempfile
import time
import urllib.request
import urllib.error

import numpy as np
import torch
from PIL import Image

log = logging.getLogger("WanVideo")

VIDEO = "VIDEO"

_T2V_MODEL  = "wan2.7-t2v"
_I2V_MODEL  = "wan2.7-i2v-2026-04-25"
_EDIT_MODEL = "wan2.7-videoedit"

_RETRY_STATUS  = {429, 500, 502, 503, 504}
_RETRY_DELAYS  = (2, 5, 12)
_RETRY_PHRASES = ("503", "502", "504", "500", "UNAVAILABLE", "Service Unavailable", "rate_limit")

_ENV_RELATIVE_PATHS = [".", "..", "../.."]

_VIDEO_PATH = "services/aigc/video-generation/video-synthesis"
_TASK_PATH  = "tasks"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _read_env_file(path: str) -> str:
    env_path = os.path.join(path, ".env")
    if not os.path.isfile(env_path):
        return ""
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == "DASHSCOPE_API_KEY":
                    return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _resolve_key(api_key_input: str) -> tuple:
    key = (api_key_input or "").strip()
    if key:
        return key, "✅ manual input"
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if key:
        return key, "✅ environment variable (DASHSCOPE_API_KEY)"
    node_dir = os.path.dirname(os.path.abspath(__file__))
    for rel in _ENV_RELATIVE_PATHS:
        key = _read_env_file(os.path.normpath(os.path.join(node_dir, rel)))
        if key:
            return key, "✅ .env file"
    return "", "❌ no key found"


def _base_url(workspace_id: str) -> str:
    ws = (workspace_id or "").strip()
    if ws:
        return f"https://{ws}.ap-southeast-1.maas.aliyuncs.com/api/v1"
    return "https://dashscope.aliyuncs.com/api/v1"


def _http_post(url: str, body: dict, api_key: str) -> dict:
    headers = {
        "Content-Type":    "application/json",
        "Authorization":   f"Bearer {api_key}",
        "X-DashScope-Async": "enable",
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"[WanVideo] HTTP {e.code}: {body_text}") from e


def _http_get(url: str, api_key: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"[WanVideo] HTTP {e.code}: {body_text}") from e


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc)
    if any(str(s) in msg for s in _RETRY_STATUS):
        return True
    return any(s in msg for s in _RETRY_PHRASES)


def _tensor_to_data_url(tensor: torch.Tensor) -> str:
    arr = (tensor.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def _video_to_data_url(video: dict) -> str:
    filepath = video.get("filepath", "")
    if not filepath or not os.path.isfile(filepath):
        raise ValueError(f"[WanVideo] video file not found: {filepath!r}")
    with open(filepath, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:video/mp4;base64,{b64}"


def _poll_video_task(base: str, task_id: str, api_key: str, max_wait: int, poll_interval: int) -> str:
    """Poll until SUCCEEDED, return video_url."""
    elapsed = 0
    while True:
        if elapsed >= max_wait:
            raise TimeoutError(
                f"[WanVideo] timed out after {max_wait}s. task_id={task_id}"
            )
        time.sleep(poll_interval)
        elapsed += poll_interval
        result = _http_get(f"{base}/{_TASK_PATH}/{task_id}", api_key)
        status = result.get("output", {}).get("task_status", "UNKNOWN")
        log.info(f"[WanVideo] task_status={status} elapsed={elapsed}s")
        if status == "SUCCEEDED":
            video_url = result.get("output", {}).get("video_url")
            if not video_url:
                raise RuntimeError("[WanVideo] SUCCEEDED but no video_url in response.")
            return video_url
        if status == "FAILED":
            msg = result.get("output", {}).get("message", "unknown error")
            raise RuntimeError(f"[WanVideo] task failed: {msg}")


def _download_video(video_url: str) -> str:
    """Download video to a temp file and return its path."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        with urllib.request.urlopen(video_url) as r:
            tmp.write(r.read())
        return tmp.name


def _submit_and_poll(base: str, body: dict, api_key: str, max_wait: int, poll_interval: int,
                     retries: int, label: str) -> str:
    """Submit task, handle retries, poll for video URL."""
    retries = max(0, min(int(retries), len(_RETRY_DELAYS)))
    url = f"{base}/{_VIDEO_PATH}"

    task_id = None
    for attempt in range(retries + 1):
        try:
            log.info(f"[{label}] POST {url} model={body.get('model')}")
            resp = _http_post(url, body, api_key)
            task_id = resp.get("output", {}).get("task_id")
            if not task_id:
                raise RuntimeError(f"[{label}] No task_id in response: {resp}")
            break
        except Exception as exc:
            if not _is_retryable(exc) or attempt >= retries:
                raise
            delay = _RETRY_DELAYS[attempt]
            log.warning(f"[{label}] transient error attempt {attempt+1}: {exc}; retry in {delay}s")
            time.sleep(delay)

    log.info(f"[{label}] task_id={task_id}, polling (max_wait={max_wait}s)…")
    return _poll_video_task(base, task_id, api_key, max_wait, poll_interval)


# ---------------------------------------------------------------------------
# WanVideo node
# ---------------------------------------------------------------------------

class WanVideo:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "Describe the video you want to generate… (required for t2v, optional for i2v)",
                }),
            },
            "optional": {
                "first_frame":   ("IMAGE",),
                "last_frame":    ("IMAGE",),
                "first_clip":    (VIDEO,),
                "api_key":       ("STRING", {
                    "default": "",
                    "password": True,
                    "tooltip": "Leave blank to use DASHSCOPE_API_KEY env var or .env file.",
                }),
                "workspace_id":  ("STRING", {
                    "default": "",
                    "tooltip": "Singapore workspace ID. Leave blank for Beijing endpoint.",
                }),
                "negative_prompt": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "Content to exclude (max 500 chars).",
                }),
                "resolution":    (["1080P", "720P"], {"default": "1080P"}),
                "ratio":         (["16:9", "9:16", "1:1", "4:3", "3:4"], {
                    "default": "16:9",
                    "tooltip": "Aspect ratio — applied for t2v only. For i2v/r2v/continuation the ratio follows the input image/clip.",
                }),
                "duration":      ("INT", {
                    "default": 5, "min": 2, "max": 15, "step": 1,
                    "tooltip": "Output duration in seconds (2–15).",
                }),
                "prompt_extend": (["true", "false"], {
                    "default": "true",
                    "tooltip": "Let the model rewrite short prompts to improve quality.",
                }),
                "watermark":     (["false", "true"], {"default": "false"}),
                "seed":          ("INT", {
                    "default": -1, "min": -1, "max": 2147483647, "step": 1,
                    "tooltip": "Random seed. -1 = random each run.",
                }),
                "max_wait":      ("INT", {"default": 600, "min": 60, "max": 1800, "step": 30}),
                "poll_interval": ("INT", {"default": 15, "min": 5,  "max": 60,   "step": 5}),
            },
        }

    RETURN_TYPES  = (VIDEO, "STRING")
    RETURN_NAMES  = ("video", "key_status")
    FUNCTION      = "generate"
    CATEGORY      = "Ranomany/Alibaba"
    OUTPUT_NODE   = False

    def generate(
        self,
        prompt:          str,
        first_frame:     torch.Tensor = None,
        last_frame:      torch.Tensor = None,
        first_clip:      dict         = None,
        api_key:         str  = "",
        workspace_id:    str  = "",
        negative_prompt: str  = "",
        resolution:      str  = "1080P",
        ratio:           str  = "16:9",
        duration:        int  = 5,
        prompt_extend:   str  = "true",
        watermark:       str  = "false",
        seed:            int  = -1,
        max_wait:        int  = 600,
        poll_interval:   int  = 15,
    ):
        key, key_status = _resolve_key(api_key)
        if not key:
            raise EnvironmentError(
                "No DashScope API key found. Pass it via the api_key input, set "
                "DASHSCOPE_API_KEY in your environment, or create a .env file with "
                "DASHSCOPE_API_KEY=... in your ComfyUI root."
            )

        base = _base_url(workspace_id)

        # Shared parameters block
        params = {
            "resolution":     resolution,
            "duration":       int(duration),
            "prompt_extend":  prompt_extend == "true",
            "watermark":      watermark == "true",
        }
        if seed >= 0:
            params["seed"] = seed

        # Determine mode and build request body
        if first_clip is not None:
            # Continuation mode — first_clip required, last_frame optional
            media = [{"type": "first_clip", "url": _video_to_data_url(first_clip)}]
            if last_frame is not None:
                lf = last_frame[0] if last_frame.ndim == 4 else last_frame
                media.append({"type": "last_frame", "url": _tensor_to_data_url(lf)})
            inp = {"prompt": prompt.strip(), "media": media}
            if negative_prompt.strip():
                inp["negative_prompt"] = negative_prompt.strip()
            body = {"model": _I2V_MODEL, "input": inp, "parameters": params}
            mode = "continuation"

        elif first_frame is not None:
            # i2v or r2v (first+last frame)
            ff = first_frame[0] if first_frame.ndim == 4 else first_frame
            media = [{"type": "first_frame", "url": _tensor_to_data_url(ff)}]
            if last_frame is not None:
                lf = last_frame[0] if last_frame.ndim == 4 else last_frame
                media.append({"type": "last_frame", "url": _tensor_to_data_url(lf)})
                mode = "r2v"
            else:
                mode = "i2v"
            inp = {"prompt": prompt.strip(), "media": media}
            if negative_prompt.strip():
                inp["negative_prompt"] = negative_prompt.strip()
            body = {"model": _I2V_MODEL, "input": inp, "parameters": params}

        else:
            # t2v — text only
            if not prompt.strip():
                raise ValueError("WanVideo: prompt is required for text-to-video (no image/clip connected).")
            inp = {"prompt": prompt.strip()}
            if negative_prompt.strip():
                inp["negative_prompt"] = negative_prompt.strip()
            params["ratio"] = ratio
            body = {"model": _T2V_MODEL, "input": inp, "parameters": params}
            mode = "t2v"

        log.info(f"[WanVideo] mode={mode} model={body['model']} resolution={resolution} duration={duration}s")

        video_url = _submit_and_poll(base, body, key, max_wait, poll_interval, retries=0, label="WanVideo")
        filepath = _download_video(video_url)
        log.info(f"[WanVideo] downloaded to {filepath}")
        return ({"filepath": filepath, "mime_type": "video/mp4"}, key_status)


# ---------------------------------------------------------------------------
# WanVideoEdit node
# ---------------------------------------------------------------------------

class WanVideoEdit:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "Describe the edit (e.g. 'Convert to claymation style')",
                }),
                "video":  (VIDEO,),
            },
            "optional": {
                "reference_image_1": ("IMAGE",),
                "reference_image_2": ("IMAGE",),
                "reference_image_3": ("IMAGE",),
                "reference_image_4": ("IMAGE",),
                "api_key":           ("STRING", {
                    "default": "",
                    "password": True,
                    "tooltip": "Leave blank to use DASHSCOPE_API_KEY env var or .env file.",
                }),
                "workspace_id":      ("STRING", {
                    "default": "",
                    "tooltip": "Singapore workspace ID. Leave blank for Beijing endpoint.",
                }),
                "negative_prompt":   ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "Content to exclude from the output (max 500 chars).",
                }),
                "resolution":        (["1080P", "720P"], {"default": "1080P"}),
                "ratio":             (["auto", "16:9", "9:16", "1:1", "4:3", "3:4"], {
                    "default": "auto",
                    "tooltip": "'auto' follows the input video's aspect ratio.",
                }),
                "duration":          ("INT", {
                    "default": 0, "min": 0, "max": 10, "step": 1,
                    "tooltip": "0 = keep input video duration; 2–10 to truncate.",
                }),
                "audio_setting":     (["auto", "origin"], {
                    "default": "auto",
                    "tooltip": "'auto' = model decides audio; 'origin' = keep original audio.",
                }),
                "prompt_extend":     (["true", "false"], {"default": "true"}),
                "watermark":         (["false", "true"], {"default": "false"}),
                "seed":              ("INT", {
                    "default": -1, "min": -1, "max": 2147483647, "step": 1,
                    "tooltip": "Random seed. -1 = random each run.",
                }),
                "max_wait":          ("INT", {"default": 600, "min": 60, "max": 1800, "step": 30}),
                "poll_interval":     ("INT", {"default": 15, "min": 5,  "max": 60,   "step": 5}),
            },
        }

    RETURN_TYPES  = (VIDEO, "STRING")
    RETURN_NAMES  = ("video", "key_status")
    FUNCTION      = "generate"
    CATEGORY      = "Ranomany/Alibaba"
    OUTPUT_NODE   = False

    def generate(
        self,
        prompt:             str,
        video:              dict,
        reference_image_1:  torch.Tensor = None,
        reference_image_2:  torch.Tensor = None,
        reference_image_3:  torch.Tensor = None,
        reference_image_4:  torch.Tensor = None,
        api_key:            str  = "",
        workspace_id:       str  = "",
        negative_prompt:    str  = "",
        resolution:         str  = "1080P",
        ratio:              str  = "auto",
        duration:           int  = 0,
        audio_setting:      str  = "auto",
        prompt_extend:      str  = "true",
        watermark:          str  = "false",
        seed:               int  = -1,
        max_wait:           int  = 600,
        poll_interval:      int  = 15,
    ):
        if not prompt.strip():
            raise ValueError("WanVideoEdit: prompt (edit instruction) is required.")

        key, key_status = _resolve_key(api_key)
        if not key:
            raise EnvironmentError(
                "No DashScope API key found. Pass it via the api_key input, set "
                "DASHSCOPE_API_KEY in your environment, or create a .env file with "
                "DASHSCOPE_API_KEY=... in your ComfyUI root."
            )

        base = _base_url(workspace_id)

        # Build media list — video first, then optional reference images
        media = [{"type": "video", "url": _video_to_data_url(video)}]
        for ref_img in [reference_image_1, reference_image_2, reference_image_3, reference_image_4]:
            if ref_img is not None:
                t = ref_img[0] if ref_img.ndim == 4 else ref_img
                media.append({"type": "reference_image", "url": _tensor_to_data_url(t)})

        inp = {"prompt": prompt.strip(), "media": media}
        if negative_prompt.strip():
            inp["negative_prompt"] = negative_prompt.strip()

        params = {
            "resolution":    resolution,
            "duration":      int(duration),
            "audio_setting": audio_setting,
            "prompt_extend": prompt_extend == "true",
            "watermark":     watermark == "true",
        }
        if ratio != "auto":
            params["ratio"] = ratio
        if seed >= 0:
            params["seed"] = seed

        body = {"model": _EDIT_MODEL, "input": inp, "parameters": params}

        log.info(f"[WanVideoEdit] resolution={resolution} duration={duration}s ref_images={len(media)-1}")

        video_url = _submit_and_poll(base, body, key, max_wait, poll_interval, retries=0, label="WanVideoEdit")
        filepath = _download_video(video_url)
        log.info(f"[WanVideoEdit] downloaded to {filepath}")
        return ({"filepath": filepath, "mime_type": "video/mp4"}, key_status)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

NODE_CLASS_MAPPINGS = {
    "WanVideo":     WanVideo,
    "WanVideoEdit": WanVideoEdit,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WanVideo":     "Wan Video Generate",
    "WanVideoEdit": "Wan Video Edit",
}

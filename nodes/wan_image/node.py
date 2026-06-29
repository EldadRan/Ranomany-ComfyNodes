"""
WanImage — ComfyUI node for Wan 2.7 image generation and editing.

Calls the Alibaba Cloud Model Studio (DashScope) API directly via raw HTTP.

API key resolution order:
  1. Value passed via the `api_key` input
  2. DASHSCOPE_API_KEY environment variable
  3. .env file — searched in the node dir, custom_nodes/, and ComfyUI root

Supports:
  - Text-to-image (prompt only)
  - Image editing / composition (prompt + one or more input images)
  - Image set generation (enable_sequential=true)

Returns a standard ComfyUI IMAGE batch tensor (B×H×W×3, float32, 0-1).

Endpoint (Beijing):  https://dashscope.aliyuncs.com/api/v1
Endpoint (Singapore): https://{workspace_id}.ap-southeast-1.maas.aliyuncs.com/api/v1
"""

import base64
import io
import json
import logging
import os
import time
import urllib.request
import urllib.error

import numpy as np
import torch
from PIL import Image

log = logging.getLogger("WanImage")

IMAGE_MODELS = ["wan2.7-image-pro", "wan2.7-image"]
DEFAULT_MODEL = "wan2.7-image-pro"

_RETRY_STATUS  = {429, 500, 502, 503, 504}
_RETRY_DELAYS  = (2, 5, 12)
_RETRY_PHRASES = ("503", "502", "504", "500", "UNAVAILABLE", "Service Unavailable", "rate_limit")

_ENV_RELATIVE_PATHS = [".", "..", "../..", "../../..", "../../../.."]

# Sync endpoint (multimodal generation)
_SYNC_PATH  = "services/aigc/multimodal-generation/generation"
# Async endpoint (image generation with task queue)
_ASYNC_PATH = "services/aigc/image-generation/generation"
# Task poll endpoint
_TASK_PATH  = "tasks"

_IMAGE_POLL_MAX  = 300   # seconds
_IMAGE_POLL_INTERVAL = 5  # seconds


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


def _http_post(url: str, body: dict, api_key: str, async_mode: bool = False) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if async_mode:
        headers["X-DashScope-Async"] = "enable"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"[WanImage] HTTP {e.code}: {body_text}") from e


def _http_get(url: str, api_key: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"[WanImage] HTTP {e.code}: {body_text}") from e


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


def _tensor_from_pil(img: Image.Image) -> torch.Tensor:
    arr = np.array(img.convert("RGB")).astype(np.float32) / 255.0
    return torch.from_numpy(arr)  # H×W×3


def _build_batch(tensors: list) -> torch.Tensor:
    if len(tensors) == 1:
        return tensors[0].unsqueeze(0)
    max_h = max(t.shape[0] for t in tensors)
    max_w = max(t.shape[1] for t in tensors)
    padded = []
    for t in tensors:
        h, w = t.shape[:2]
        if h < max_h or w < max_w:
            pad = torch.zeros(max_h, max_w, 3, dtype=t.dtype)
            pad[:h, :w] = t
            padded.append(pad)
        else:
            padded.append(t)
    return torch.stack(padded, dim=0)


def _extract_images_from_choices(choices: list) -> list:
    """Extract image URLs from the API choices response structure."""
    urls = []
    for choice in choices:
        content = choice.get("message", {}).get("content", [])
        for item in content:
            if item.get("type") == "image" and item.get("image"):
                urls.append(item["image"])
    return urls


def _download_url(url: str) -> bytes:
    with urllib.request.urlopen(url) as r:
        return r.read()


_PRESETS = {"1k", "2k", "4k"}

def _validate_size(size: str, has_image: bool) -> str:
    """Normalise and validate the size param. Returns the value to send to the API."""
    s = size.strip()
    if s.upper() in {p.upper() for p in _PRESETS}:
        return s.upper()

    # Expect W*H  (asterisk or x)
    s_norm = s.replace("x", "*").replace("X", "*").replace("×", "*")
    parts = s_norm.split("*")
    if len(parts) != 2:
        raise ValueError(
            f"WanImage: invalid size '{size}'. Use a preset (1K, 2K, 4K) or W*H format (e.g. 1280*720)."
        )
    try:
        w, h = int(parts[0].strip()), int(parts[1].strip())
    except ValueError:
        raise ValueError(f"WanImage: size '{size}' — width and height must be integers.")

    # Ratio check (1:8 to 8:1)
    ratio = max(w, h) / min(w, h)
    if ratio > 8.0:
        raise ValueError(
            f"WanImage: aspect ratio {max(w,h)}:{min(w,h)} ({ratio:.2f}:1) exceeds the 8:1 limit."
        )

    # Pixel count check
    pixels = w * h
    min_px = 768 * 768
    max_px = (2048 * 2048) if has_image else (4096 * 4096)
    mode_label = "image editing" if has_image else "text-to-image"
    if pixels < min_px:
        raise ValueError(
            f"WanImage: {w}×{h} = {pixels:,} pixels is below the minimum of {min_px:,} (768×768)."
        )
    if pixels > max_px:
        raise ValueError(
            f"WanImage: {w}×{h} = {pixels:,} pixels exceeds the {mode_label} maximum of {max_px:,} pixels."
        )

    return f"{w}*{h}"


class WanImage:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "Describe the image you want to generate…",
                }),
                "model": (IMAGE_MODELS, {"default": DEFAULT_MODEL}),
            },
            "optional": {
                "image":            ("IMAGE",),
                "api_key":          ("STRING", {
                    "default": "",
                    "password": True,
                    "tooltip": "Leave blank to use DASHSCOPE_API_KEY env var or .env file.",
                }),
                "workspace_id":     ("STRING", {
                    "default": "",
                    "tooltip": "Singapore workspace ID (e.g. ws-xxxxxxxx). Leave blank for Beijing endpoint.",
                }),
                "width":            ("INT", {
                    "default": 1024, "min": 64, "max": 4096, "step": 8,
                    "tooltip": "Output width in pixels (t2i). Auto-read from input image when image editing.",
                }),
                "height":           ("INT", {
                    "default": 1024, "min": 64, "max": 4096, "step": 8,
                    "tooltip": "Output height in pixels (t2i). Auto-read from input image when image editing.",
                }),
                "n":                ("INT", {"default": 1, "min": 1, "max": 4, "step": 1,
                                             "tooltip": "Number of images to generate (1-4, or up to 12 in image set mode)."}),
                "thinking_mode":    (["true", "false"], {
                    "default": "true",
                    "tooltip": "Enhance generation quality (wan2.7-image-pro, text-to-image only). Increases latency.",
                }),
                "enable_sequential": (["false", "true"], {
                    "default": "false",
                    "tooltip": "Image set mode — generate a coherent sequence of images from one prompt.",
                }),
                "watermark":        (["false", "true"], {"default": "false"}),
                "seed":             ("INT", {
                    "default": -1, "min": -1, "max": 2147483647, "step": 1,
                    "tooltip": "Random seed. -1 = random each run.",
                }),
                "retries":          ("INT", {"default": 0, "min": 0, "max": 3, "step": 1}),
            },
        }

    RETURN_TYPES  = ("IMAGE", "STRING")
    RETURN_NAMES  = ("images", "key_status")
    FUNCTION      = "generate"
    CATEGORY      = "Ranomany/Alibaba"
    OUTPUT_NODE   = False

    def generate(
        self,
        prompt:           str,
        model:            str  = DEFAULT_MODEL,
        image:            torch.Tensor = None,
        api_key:          str  = "",
        workspace_id:     str  = "",
        width:            int  = 1024,
        height:           int  = 1024,
        n:                int  = 1,
        thinking_mode:    str  = "true",
        enable_sequential: str = "false",
        watermark:        str  = "false",
        seed:             int  = -1,
        retries:          int  = 0,
    ):
        if not prompt.strip() and image is None:
            raise ValueError("WanImage: provide a prompt and/or an input image.")

        key, key_status = _resolve_key(api_key)
        if not key:
            raise EnvironmentError(
                "No DashScope API key found. Pass it via the api_key input, set "
                "DASHSCOPE_API_KEY in your environment, or create a .env file with "
                "DASHSCOPE_API_KEY=... in your ComfyUI root."
            )

        base = _base_url(workspace_id)

        # When an image is connected, use its dimensions instead of the widgets
        if image is not None:
            if image.ndim == 3:
                image = image.unsqueeze(0)
            h_px, w_px = image.shape[1], image.shape[2]
        else:
            w_px, h_px = int(width), int(height)

        validated_size = _validate_size(f"{w_px}*{h_px}", has_image=image is not None)

        # Build messages content
        content = []
        if prompt.strip():
            content.append({"text": prompt.strip()})

        if image is not None:
            n_frames = min(image.shape[0], 9)  # API limit: max 9 images
            for i in range(n_frames):
                content.append({"image": _tensor_to_data_url(image[i])})

        body = {
            "model": model,
            "input": {
                "messages": [{"role": "user", "content": content}]
            },
            "parameters": {
                "size":             validated_size,
                "n":                int(n),
                "watermark":        watermark == "true",
                "enable_sequential": enable_sequential == "true",
            },
        }

        # thinking_mode only applies to pro model in t2i mode (no image input)
        if model == "wan2.7-image-pro" and image is None and enable_sequential == "false":
            body["parameters"]["thinking_mode"] = thinking_mode == "true"

        if seed >= 0:
            body["parameters"]["seed"] = seed

        retries = max(0, min(int(retries), len(_RETRY_DELAYS)))

        def _call():
            # Try synchronous first
            sync_url = f"{base}/{_SYNC_PATH}"
            log.info(f"[WanImage] POST {sync_url} model={model} size={validated_size} n={n}")
            resp = _http_post(sync_url, body, key, async_mode=False)

            output = resp.get("output", {})

            # If we got a task_id, poll for result
            if "task_id" in output:
                task_id = output["task_id"]
                log.info(f"[WanImage] async task_id={task_id}, polling…")
                return _poll_image_task(base, task_id, key)

            # Synchronous result — extract images from choices
            choices = output.get("choices", [])
            return _extract_images_from_choices(choices)

        def _poll_image_task(base: str, task_id: str, key: str) -> list:
            elapsed = 0
            while True:
                if elapsed >= _IMAGE_POLL_MAX:
                    raise TimeoutError(
                        f"[WanImage] timed out after {_IMAGE_POLL_MAX}s (task_id={task_id})"
                    )
                time.sleep(_IMAGE_POLL_INTERVAL)
                elapsed += _IMAGE_POLL_INTERVAL
                result = _http_get(f"{base}/{_TASK_PATH}/{task_id}", key)
                status = result.get("output", {}).get("task_status", "UNKNOWN")
                log.info(f"[WanImage] task_status={status} elapsed={elapsed}s")
                if status == "SUCCEEDED":
                    choices = result.get("output", {}).get("choices", [])
                    return _extract_images_from_choices(choices)
                if status == "FAILED":
                    msg = result.get("output", {}).get("message", "unknown error")
                    raise RuntimeError(f"[WanImage] task failed: {msg}")

        image_urls = None
        for attempt in range(retries + 1):
            try:
                image_urls = _call()
                break
            except Exception as exc:
                if not _is_retryable(exc) or attempt >= retries:
                    raise
                delay = _RETRY_DELAYS[attempt]
                log.warning(f"[WanImage] transient error attempt {attempt+1}: {exc}; retry in {delay}s")
                time.sleep(delay)

        if not image_urls:
            raise RuntimeError("WanImage: no images returned by the API.")

        tensors = []
        for url in image_urls:
            raw = _download_url(url)
            pil = Image.open(io.BytesIO(raw)).convert("RGB")
            tensors.append(_tensor_from_pil(pil))

        return (_build_batch(tensors), key_status)


NODE_CLASS_MAPPINGS = {
    "WanImage": WanImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WanImage": "Wan Image Generate",
}

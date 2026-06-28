"""
GeminiImage — ComfyUI node for Gemini image generation / editing.

Calls the Gemini API directly (google-genai SDK).

API key resolution order:
  1. Value passed via the `api_key` input (or wired from a GeminiAPIKey node)
  2. GEMINI_API_KEY environment variable
  3. .env file — searched in the node dir, custom_nodes/, and ComfyUI root

Supports:
  - Text-to-image (prompt only)
  - Image editing / composition (prompt + one or more input images)
  - Flash model (fast, cheap) or Pro model (highest quality with thinking)

Returns a standard ComfyUI IMAGE batch tensor (B×H×W×3, float32, 0-1).
"""

import os
import base64
import time
import logging

import numpy as np
from PIL import Image
import io
import torch

log = logging.getLogger("GeminiImage")

DEFAULT_FLASH = "gemini-3.1-flash-image-preview"
DEFAULT_PRO   = "gemini-3-pro-image-preview"

IMAGE_MODELS = [
    DEFAULT_FLASH,
    DEFAULT_PRO,
]

_RETRY_STATUS  = {429, 500, 502, 503, 504}
_RETRY_DELAYS  = (2, 5, 12)
_RETRY_PHRASES = ("503", "502", "504", "500", "UNAVAILABLE", "Service Unavailable")

# .env search path: node dir → custom_nodes/ → ComfyUI root
_ENV_RELATIVE_PATHS = [".", "..", "../.."]


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
                if k.strip() == "GEMINI_API_KEY":
                    return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _resolve_key(api_key_input: str) -> tuple:
    key = (api_key_input or "").strip()
    if key:
        return key, "✅ manual input"
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key, "✅ environment variable (GEMINI_API_KEY)"
    node_dir = os.path.dirname(os.path.abspath(__file__))
    for rel in _ENV_RELATIVE_PATHS:
        key = _read_env_file(os.path.normpath(os.path.join(node_dir, rel)))
        if key:
            return key, "✅ .env file"
    return "", "❌ no key found"


def _get_client(api_key: str):
    from google import genai
    key, status = _resolve_key(api_key)
    if not key:
        raise EnvironmentError(
            "No Gemini API key found. Pass it via the api_key input, set "
            "GEMINI_API_KEY in your environment, or create a .env file with "
            "GEMINI_API_KEY=... in your ComfyUI root."
        )
    return genai.Client(api_key=key), status


def _is_retryable(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in _RETRY_STATUS:
        return True
    msg = str(exc)
    return any(s in msg for s in _RETRY_PHRASES)


def _tensor_from_pil(img: Image.Image) -> torch.Tensor:
    arr = np.array(img.convert("RGB")).astype(np.float32) / 255.0
    return torch.from_numpy(arr)  # H×W×3


class GeminiImage:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "Describe the image you want to generate…",
                }),
                "model": (IMAGE_MODELS, {"default": DEFAULT_FLASH}),
            },
            "optional": {
                "image":          ("IMAGE",),
                "api_key":        ("STRING", {"default": "", "password": True, "tooltip": "Leave blank to use GEMINI_API_KEY env var or .env file. Wire from a GeminiAPIKey node for shared key management."}),
                "image_size":     (["1K", "2K", "4K"], {"default": "1K"}),
                "aspect_ratio":   (["none", "1:1", "16:9", "9:16", "4:3", "3:4"], {"default": "none"}),
                "thinking_level": (["low", "high"], {"default": "low"}),
                "retries":        ("INT", {"default": 0, "min": 0, "max": 3, "step": 1}),
            },
        }

    RETURN_TYPES    = ("IMAGE", "STRING")
    RETURN_NAMES    = ("images", "key_status")
    FUNCTION        = "generate"
    CATEGORY        = "Ranomany/Gemini"
    OUTPUT_NODE     = False

    def generate(
        self,
        prompt:         str,
        model:          str  = DEFAULT_FLASH,
        image:          torch.Tensor = None,
        api_key:        str  = "",
        image_size:     str  = "1K",
        aspect_ratio:   str  = "none",
        thinking_level: str  = "low",
        retries:        int  = 0,
    ):
        from google.genai import types

        if not prompt.strip() and image is None:
            raise ValueError("GeminiImage: provide a prompt and/or an input image.")

        client, key_status = _get_client(api_key)

        # Build contents list
        contents = []

        # Convert input IMAGE tensor → base64 PNG part(s)
        if image is not None:
            # image shape: B×H×W×3 or H×W×3
            if image.ndim == 3:
                image = image.unsqueeze(0)
            for i in range(image.shape[0]):
                arr  = (image[i].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
                pil  = Image.fromarray(arr)
                buf  = io.BytesIO()
                pil.save(buf, format="PNG")
                b64  = base64.b64encode(buf.getvalue()).decode("utf-8")
                contents.append(
                    types.Part.from_bytes(data=base64.b64decode(b64), mime_type="image/png")
                )

        if prompt.strip():
            contents.append(prompt.strip())

        if not contents:
            raise ValueError("GeminiImage: nothing to send — provide a prompt or image.")

        # Build generation config
        img_cfg_kwargs = {}
        if image_size and image_size != "none":
            img_cfg_kwargs["image_size"] = image_size.upper()
        if aspect_ratio and aspect_ratio != "none":
            img_cfg_kwargs["aspect_ratio"] = aspect_ratio

        gen_config_kwargs = {
            "response_modalities": ["IMAGE", "TEXT"],
        }
        if img_cfg_kwargs:
            gen_config_kwargs["image_config"] = types.ImageConfig(**img_cfg_kwargs)
        if "pro" in model:
            gen_config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=thinking_level)

        gen_config = types.GenerateContentConfig(**gen_config_kwargs)

        # Call with retry
        retries = max(0, min(int(retries), len(_RETRY_DELAYS)))
        response = None
        for attempt in range(retries + 1):
            try:
                response = client.models.generate_content(
                    model=model, contents=contents, config=gen_config,
                )
                break
            except Exception as exc:
                if not _is_retryable(exc) or attempt >= retries:
                    raise
                delay = _RETRY_DELAYS[attempt]
                log.warning(f"[GeminiImage] transient error attempt {attempt+1}: {exc}; retry in {delay}s")
                time.sleep(delay)

        # Extract image parts
        tensors = []
        for part in response.parts:
            if part.inline_data and part.inline_data.data:
                pil = Image.open(io.BytesIO(part.inline_data.data)).convert("RGB")
                tensors.append(_tensor_from_pil(pil))

        if not tensors:
            text_parts = [p.text for p in response.parts if p.text]
            raise RuntimeError(
                "GeminiImage: no images returned. "
                f"Model said: {' '.join(text_parts) or '(nothing)'}"
            )

        # Stack into B×H×W×3 batch
        # Pad smaller images to the largest if sizes differ
        if len(tensors) > 1:
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
            batch = torch.stack(padded, dim=0)
        else:
            batch = tensors[0].unsqueeze(0)

        return (batch, key_status)


NODE_CLASS_MAPPINGS = {
    "GeminiImage": GeminiImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "GeminiImage": "Gemini Image Generate",
}

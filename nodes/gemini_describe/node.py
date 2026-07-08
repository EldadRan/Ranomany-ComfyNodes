"""
GeminiDescribe — ComfyUI node: image + prompt → text description (Gemini vision).

Uses Gemini 3.1 Flash Lite (a fast, cheap text model with vision) via the
google-genai SDK to caption / describe / answer questions about an input image.
Output is a STRING (wire it to any text sink, a Show Text node, or metadata).

API key resolution order (same as the other Gemini nodes):
  1. Value passed via the `api_key` input (or wired from a GeminiAPIKey node)
  2. GEMINI_API_KEY environment variable
  3. .env file — searched in the node dir, custom_nodes/, and ComfyUI root
"""

import os
import io
import time
import logging

import numpy as np
from PIL import Image
import torch

log = logging.getLogger("GeminiDescribe")

# Gemini 3.1 Flash Lite — fast/cheap vision-capable text model. Editable in case
# the exact published id differs in your account/region.
DEFAULT_MODEL = "gemini-3.1-flash-lite"

_DEFAULT_PROMPT = "Describe this image in detail."

_RETRY_STATUS  = {429, 500, 502, 503, 504}
_RETRY_DELAYS  = (2, 5, 12)
_RETRY_PHRASES = ("503", "502", "504", "500", "UNAVAILABLE", "Service Unavailable")

# .env search path: node dir → custom_nodes/ → ComfyUI root
_ENV_RELATIVE_PATHS = [".", "..", "../..", "../../..", "../../../.."]


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


def _image_parts(image: torch.Tensor):
    """A ComfyUI IMAGE tensor (B×H×W×3 or H×W×3) → list of PNG image Parts."""
    from google.genai import types
    if image.ndim == 3:
        image = image.unsqueeze(0)
    parts = []
    for i in range(image.shape[0]):
        arr = (image[i].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        buf = io.BytesIO()
        Image.fromarray(arr).save(buf, format="PNG")
        parts.append(types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png"))
    return parts


class GeminiDescribe:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {"tooltip": "Image to describe."}),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": _DEFAULT_PROMPT,
                    "placeholder": "What should the model describe or answer about the image?",
                }),
            },
            "optional": {
                "model": ("STRING", {
                    "default": DEFAULT_MODEL,
                    "tooltip": "Gemini text model id (vision-capable). Default: Gemini 3.1 Flash Lite.",
                }),
                "api_key": ("STRING", {
                    "default": "", "password": True,
                    "tooltip": "Leave blank to use GEMINI_API_KEY env var or .env file.",
                }),
                "system_instruction": ("STRING", {
                    "multiline": True, "default": "",
                    "tooltip": "Optional system instruction to steer tone/format.",
                }),
                "retries": ("INT", {"default": 0, "min": 0, "max": 3, "step": 1}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("description", "key_status")
    FUNCTION     = "describe"
    CATEGORY     = "Ranomany/Gemini"
    OUTPUT_NODE  = False

    def describe(self, image, prompt=_DEFAULT_PROMPT, model=DEFAULT_MODEL,
                 api_key="", system_instruction="", retries=0):
        from google.genai import types

        if image is None:
            raise ValueError("GeminiDescribe: an input `image` is required.")
        if not prompt.strip():
            raise ValueError("GeminiDescribe: a prompt is required.")

        client, key_status = _get_client(api_key)

        contents = _image_parts(image)
        contents.append(prompt.strip())

        gen_config_kwargs = {"response_modalities": ["TEXT"]}
        if system_instruction.strip():
            gen_config_kwargs["system_instruction"] = system_instruction.strip()
        gen_config = types.GenerateContentConfig(**gen_config_kwargs)

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
                log.warning(f"[GeminiDescribe] transient error attempt {attempt+1}: {exc}; retry in {delay}s")
                time.sleep(delay)

        text = (getattr(response, "text", None) or "").strip()
        if not text:
            # Fall back to concatenating any text parts.
            parts = getattr(response, "parts", None) or []
            text = " ".join(p.text for p in parts if getattr(p, "text", None)).strip()
        if not text:
            raise RuntimeError("GeminiDescribe: model returned no text.")

        log.info(f"[GeminiDescribe] model={model} chars={len(text)}")
        return (text, key_status)


NODE_CLASS_MAPPINGS = {
    "GeminiDescribe": GeminiDescribe,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "GeminiDescribe": "Gemini Describe Image",
}

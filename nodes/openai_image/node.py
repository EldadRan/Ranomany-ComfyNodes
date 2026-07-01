"""
OpenAIImage — ComfyUI node for gpt-image-2 (ChatGPT Images 2.0) generation / editing.

Calls the OpenAI Images API directly (openai SDK).

API key resolution order:
  1. Value passed via the `api_key` input (or wired from an API Key node)
  2. OPENAI_API_KEY environment variable
  3. .env file — searched in the node dir, custom_nodes/, and ComfyUI root

Supports:
  - Text-to-image (prompt only)
  - Image editing / inpainting (prompt + image + optional mask)

Returns a standard ComfyUI IMAGE batch tensor (B×H×W×3, float32, 0-1).
"""

import base64
import io
import logging
import os
import time

import numpy as np
import torch
from PIL import Image

log = logging.getLogger("OpenAIImage")

IMAGE_MODELS = ["gpt-image-2"]
DEFAULT_MODEL = "gpt-image-2"

_RETRY_STATUS  = {429, 500, 502, 503, 504}
_RETRY_DELAYS  = (2, 5, 12)
_RETRY_PHRASES = ("503", "502", "504", "500", "UNAVAILABLE", "Service Unavailable", "rate_limit")

_ENV_RELATIVE_PATHS = [".", "..", "../..", "../../..", "../../../.."]

# gpt-image-2 size constraints
_MAX_EDGE    = 3840
_MIN_PIXELS  = 655_360
_MAX_PIXELS  = 8_294_400
_MAX_RATIO   = 3.0


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
                if k.strip() == "OPENAI_API_KEY":
                    return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _resolve_key(api_key_input: str) -> tuple:
    key = (api_key_input or "").strip()
    if key:
        return key, "✅ manual input"
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key, "✅ environment variable (OPENAI_API_KEY)"
    node_dir = os.path.dirname(os.path.abspath(__file__))
    for rel in _ENV_RELATIVE_PATHS:
        key = _read_env_file(os.path.normpath(os.path.join(node_dir, rel)))
        if key:
            return key, "✅ .env file"
    return "", "❌ no key found"


def _get_client(api_key: str):
    import openai
    key, status = _resolve_key(api_key)
    if not key:
        raise EnvironmentError(
            "No OpenAI API key found. Pass it via the api_key input, set "
            "OPENAI_API_KEY in your environment, or create a .env file with "
            "OPENAI_API_KEY=... in your ComfyUI root."
        )
    return openai.OpenAI(api_key=key), status


def _is_retryable(exc: Exception) -> bool:
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if code in _RETRY_STATUS:
        return True
    msg = str(exc)
    return any(s in msg for s in _RETRY_PHRASES)


def _tensor_to_png_bytes(tensor: torch.Tensor) -> bytes:
    """Convert a ComfyUI IMAGE tensor (H×W×3 float32 0-1) to PNG bytes."""
    arr = (tensor.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def _tensor_and_mask_to_rgba_bytes(image_tensor: torch.Tensor, mask_tensor: torch.Tensor) -> bytes:
    """
    Compose an RGBA PNG for OpenAI's edit mask format.
    OpenAI: alpha=0 means 'edit here', alpha=255 means 'keep'.
    ComfyUI mask: 1=edit-here, 0=keep — so alpha = (1 - mask) * 255.
    Mask is resized to match the image if their dimensions differ.
    """
    img_arr  = (image_tensor.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)  # H×W×3
    mask_arr = mask_tensor.cpu().numpy()  # H×W (possibly 1×H×W)
    if mask_arr.ndim == 3:
        mask_arr = mask_arr[0]

    img_h, img_w = img_arr.shape[:2]
    if mask_arr.shape != (img_h, img_w):
        mask_pil = Image.fromarray((mask_arr * 255).clip(0, 255).astype(np.uint8), mode="L")
        mask_pil = mask_pil.resize((img_w, img_h), Image.LANCZOS)
        mask_arr = np.array(mask_pil).astype(np.float32) / 255.0

    alpha = ((1.0 - mask_arr) * 255).clip(0, 255).astype(np.uint8)
    rgba  = np.dstack([img_arr, alpha])  # H×W×4
    buf   = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG")
    return buf.getvalue()


import math as _math


def _snap16(v: int) -> int:
    """Round to nearest multiple of 16, minimum 16."""
    return max(16, round(v / 16) * 16)


def _snap16_up(v: int) -> int:
    """Round UP to nearest multiple of 16, minimum 16."""
    return max(16, _math.ceil(v / 16) * 16)


def _autocorrect_size(w: int, h: int) -> tuple:
    """
    Clamp w×h to gpt-image-2 constraints and return (w, h, size_str, warnings).
    Rules:
      - Both dims multiple of 16
      - Max edge 3840px
      - Ratio long:short ≤ 3:1  (strict — API rejects anything above)
      - Total pixels 655,360 – 8,294,400
    """
    warnings = []
    orig = (w, h)

    # Snap to multiple of 16
    w, h = _snap16(w), _snap16(h)

    # Clamp max edge
    w = min(w, _MAX_EDGE)
    h = min(h, _MAX_EDGE)

    # Enforce 3:1 ratio — round the short edge UP so ratio stays ≤ 3.0 after snapping.
    # Must use ceil (not round) because rounding down keeps ratio above 3:1.
    if w > 0 and h > 0:
        if w >= h and w / h > _MAX_RATIO:
            h = _snap16_up(_math.ceil(w / _MAX_RATIO))
        elif h > w and h / w > _MAX_RATIO:
            w = _snap16_up(_math.ceil(h / _MAX_RATIO))

    # Enforce pixel minimum — scale both up proportionally
    pixels = w * h
    if pixels < _MIN_PIXELS:
        scale = (_MIN_PIXELS / pixels) ** 0.5
        w = _snap16(int(w * scale))
        h = _snap16(int(h * scale))
        w = min(w, _MAX_EDGE)
        h = min(h, _MAX_EDGE)

    # Enforce pixel maximum — scale both down proportionally
    pixels = w * h
    if pixels > _MAX_PIXELS:
        scale = (_MAX_PIXELS / pixels) ** 0.5
        w = _snap16(int(w * scale))
        h = _snap16(int(h * scale))

    if (w, h) != orig:
        warnings.append(
            f"[OpenAIImage] size auto-corrected: {orig[0]}×{orig[1]} → {w}×{h} "
            f"(ratio={max(w,h)/min(w,h):.2f}:1, pixels={w*h:,})"
        )

    return w, h, f"{w}x{h}", warnings


def _tensor_from_pil(img: Image.Image) -> torch.Tensor:
    arr = np.array(img.convert("RGB")).astype(np.float32) / 255.0
    return torch.from_numpy(arr)  # H×W×3


class OpenAIImage:

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
                "image":              ("IMAGE",),
                "mask":               ("MASK",),
                "api_key":            ("STRING", {
                    "default": "",
                    "password": True,
                    "tooltip": "Leave blank to use OPENAI_API_KEY env var or .env file.",
                }),
                "width":              ("INT", {
                    "default": 1024, "min": 64, "max": 3840, "step": 16,
                    "display": "number",
                    "tooltip": "Output width in pixels. Snapped to nearest multiple of 16. Max 3840px. Ratio and pixel-count limits auto-corrected before the API call.",
                }),
                "height":             ("INT", {
                    "default": 1024, "min": 64, "max": 3840, "step": 16,
                    "display": "number",
                    "tooltip": "Output height in pixels. Snapped to nearest multiple of 16. Max 3840px. Ratio and pixel-count limits auto-corrected before the API call.",
                }),
                "quality":            (["auto", "low", "medium", "high"], {"default": "auto"}),
                "background":         (["auto", "opaque"], {"default": "auto"}),
                "output_format":      (["png", "jpeg", "webp"], {"default": "png"}),
                "output_compression": ("INT", {
                    "default": 85, "min": 0, "max": 100, "step": 1,
                    "tooltip": "Compression level for jpeg/webp (0–100). Ignored for png.",
                }),
                "moderation":         (["auto", "low"], {"default": "auto"}),
                "n":                  ("INT", {"default": 1, "min": 1, "max": 10, "step": 1}),
                "retries":            ("INT", {"default": 0, "min": 0, "max": 3, "step": 1}),
            },
        }

    RETURN_TYPES  = ("IMAGE", "STRING")
    RETURN_NAMES  = ("images", "key_status")
    FUNCTION      = "generate"
    CATEGORY      = "Ranomany/OpenAI"
    OUTPUT_NODE   = False

    def generate(
        self,
        prompt:             str,
        model:              str  = DEFAULT_MODEL,
        image:              torch.Tensor = None,
        mask:               torch.Tensor = None,
        api_key:            str  = "",
        width:              int  = 1024,
        height:             int  = 1024,
        quality:            str  = "auto",
        background:         str  = "auto",
        output_format:      str  = "png",
        output_compression: int  = 85,
        moderation:         str  = "auto",
        n:                  int  = 1,
        retries:            int  = 0,
    ):
        if not prompt.strip() and image is None:
            raise ValueError("OpenAIImage: provide a prompt and/or an input image.")

        width, height, size, size_warnings = _autocorrect_size(int(width), int(height))
        for w in size_warnings:
            log.warning(w)

        client, key_status = _get_client(api_key)

        edit_mode = image is not None

        retries = max(0, min(int(retries), len(_RETRY_DELAYS)))

        def _call():
            if edit_mode:
                # Prepare image file-like object
                if image.ndim == 4:
                    img_tensor = image[0]
                else:
                    img_tensor = image
                img_bytes = _tensor_to_png_bytes(img_tensor)
                img_file  = io.BytesIO(img_bytes)
                img_file.name = "image.png"

                # Prepare optional mask
                mask_file = None
                if mask is not None:
                    mask_t = mask
                    rgba_bytes = _tensor_and_mask_to_rgba_bytes(img_tensor, mask_t)
                    mask_file  = io.BytesIO(rgba_bytes)
                    mask_file.name = "mask.png"

                kwargs = dict(
                    model=model,
                    image=img_file,
                    prompt=prompt.strip(),
                    size=size,
                    n=int(n),
                )
                if mask_file is not None:
                    kwargs["mask"] = mask_file

                log.info(f"[OpenAIImage] edit: {width}×{height} n={n}")
                return client.images.edit(**kwargs)
            else:
                kwargs = dict(
                    model=model,
                    prompt=prompt.strip(),
                    size=size,
                    quality=quality,
                    background=background,
                    output_format=output_format,
                    n=int(n),
                    moderation=moderation,
                )
                if output_format in ("jpeg", "webp"):
                    kwargs["output_compression"] = int(output_compression)

                log.info(f"[OpenAIImage] generate: {width}×{height} quality={quality} n={n}")
                return client.images.generate(**kwargs)

        response = None
        for attempt in range(retries + 1):
            try:
                response = _call()
                break
            except Exception as exc:
                if not _is_retryable(exc) or attempt >= retries:
                    raise
                delay = _RETRY_DELAYS[attempt]
                log.warning(f"[OpenAIImage] transient error attempt {attempt+1}: {exc}; retry in {delay}s")
                time.sleep(delay)

        tensors = []
        for item in response.data:
            if item.b64_json:
                raw = base64.b64decode(item.b64_json)
            elif item.url:
                import urllib.request
                with urllib.request.urlopen(item.url) as resp:
                    raw = resp.read()
            else:
                raise RuntimeError("OpenAIImage: response item has neither b64_json nor url.")
            pil = Image.open(io.BytesIO(raw)).convert("RGB")
            tensors.append(_tensor_from_pil(pil))

        if not tensors:
            raise RuntimeError("OpenAIImage: no images returned by the API.")

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


_MAX_EDIT_IMAGES = 16


class OpenAIImageMultiRef:
    """gpt-image-2 editing with a mandatory first image + up to 3 optional reference images.

    Always runs in edit mode: `image` is required and sent first (gpt-image
    preserves the first image with the highest fidelity), and `image_2`/`image_3`/
    `image_4` are appended as extra reference images. The OpenAI images.edit
    endpoint accepts up to 16 images as an array. Optional `mask` applies to the
    first image.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "Describe the edit / composition you want…",
                }),
                "model": (IMAGE_MODELS, {"default": DEFAULT_MODEL}),
                "image": ("IMAGE", {"tooltip": "Primary image — sent first, preserved with highest fidelity."}),
            },
            "optional": {
                "image_2":  ("IMAGE", {"tooltip": "Optional reference image."}),
                "image_3":  ("IMAGE", {"tooltip": "Optional reference image."}),
                "image_4":  ("IMAGE", {"tooltip": "Optional reference image."}),
                "mask":     ("MASK", {"tooltip": "Optional edit mask for the primary image."}),
                "api_key":  ("STRING", {
                    "default": "",
                    "password": True,
                    "tooltip": "Leave blank to use OPENAI_API_KEY env var or .env file.",
                }),
                "width":    ("INT", {
                    "default": 1024, "min": 64, "max": 3840, "step": 16,
                    "display": "number",
                    "tooltip": "Output width in pixels. Snapped to nearest multiple of 16. Max 3840px. Ratio and pixel-count limits auto-corrected before the API call.",
                }),
                "height":   ("INT", {
                    "default": 1024, "min": 64, "max": 3840, "step": 16,
                    "display": "number",
                    "tooltip": "Output height in pixels. Snapped to nearest multiple of 16. Max 3840px. Ratio and pixel-count limits auto-corrected before the API call.",
                }),
                "n":        ("INT", {"default": 1, "min": 1, "max": 10, "step": 1}),
                "retries":  ("INT", {"default": 0, "min": 0, "max": 3, "step": 1}),
            },
        }

    RETURN_TYPES  = ("IMAGE", "STRING")
    RETURN_NAMES  = ("images", "key_status")
    FUNCTION      = "generate"
    CATEGORY      = "Ranomany/OpenAI"
    OUTPUT_NODE   = False

    def generate(
        self,
        prompt:   str,
        model:    str  = DEFAULT_MODEL,
        image:    torch.Tensor = None,
        image_2:  torch.Tensor = None,
        image_3:  torch.Tensor = None,
        image_4:  torch.Tensor = None,
        mask:     torch.Tensor = None,
        api_key:  str  = "",
        width:    int  = 1024,
        height:   int  = 1024,
        n:        int  = 1,
        retries:  int  = 0,
    ):
        if image is None:
            raise ValueError("OpenAIImageMultiRef: the primary `image` input is required.")

        width, height, size, size_warnings = _autocorrect_size(int(width), int(height))
        for w in size_warnings:
            log.warning(w)

        client, key_status = _get_client(api_key)

        # Flatten all provided images (in order) into a list of PNG file objects.
        first_frame = None
        image_files = []
        for img in (image, image_2, image_3, image_4):
            if img is None:
                continue
            frames = img if img.ndim == 4 else img.unsqueeze(0)
            for i in range(frames.shape[0]):
                frame = frames[i]
                if first_frame is None:
                    first_frame = frame
                f = io.BytesIO(_tensor_to_png_bytes(frame))
                f.name = f"image{len(image_files)}.png"
                image_files.append(f)

        if len(image_files) > _MAX_EDIT_IMAGES:
            log.warning(
                f"[OpenAIImageMultiRef] {len(image_files)} images provided; "
                f"OpenAI accepts at most {_MAX_EDIT_IMAGES} — using the first {_MAX_EDIT_IMAGES}."
            )
            image_files = image_files[:_MAX_EDIT_IMAGES]

        # Optional mask applies to the first image.
        mask_file = None
        if mask is not None:
            rgba_bytes = _tensor_and_mask_to_rgba_bytes(first_frame, mask)
            mask_file = io.BytesIO(rgba_bytes)
            mask_file.name = "mask.png"

        retries = max(0, min(int(retries), len(_RETRY_DELAYS)))

        def _call():
            kwargs = dict(
                model=model,
                image=image_files,
                prompt=prompt.strip(),
                size=size,
                n=int(n),
            )
            if mask_file is not None:
                mask_file.seek(0)
                kwargs["mask"] = mask_file
            for f in image_files:
                f.seek(0)
            log.info(f"[OpenAIImageMultiRef] edit: {width}×{height} images={len(image_files)} n={n}")
            return client.images.edit(**kwargs)

        response = None
        for attempt in range(retries + 1):
            try:
                response = _call()
                break
            except Exception as exc:
                if not _is_retryable(exc) or attempt >= retries:
                    raise
                delay = _RETRY_DELAYS[attempt]
                log.warning(f"[OpenAIImageMultiRef] transient error attempt {attempt+1}: {exc}; retry in {delay}s")
                time.sleep(delay)

        tensors = []
        for item in response.data:
            if item.b64_json:
                raw = base64.b64decode(item.b64_json)
            elif item.url:
                import urllib.request
                with urllib.request.urlopen(item.url) as resp:
                    raw = resp.read()
            else:
                raise RuntimeError("OpenAIImageMultiRef: response item has neither b64_json nor url.")
            pil = Image.open(io.BytesIO(raw)).convert("RGB")
            tensors.append(_tensor_from_pil(pil))

        if not tensors:
            raise RuntimeError("OpenAIImageMultiRef: no images returned by the API.")

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
    "OpenAIImage": OpenAIImage,
    "OpenAIImageMultiRef": OpenAIImageMultiRef,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "OpenAIImage": "OpenAI Image Generate",
    "OpenAIImageMultiRef": "OpenAI Image Edit (Multi-Ref)",
}

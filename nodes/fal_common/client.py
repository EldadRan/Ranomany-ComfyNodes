"""
fal_common — shared transport for every fal.ai node in this bundle.

fal.ai models all speak the same queue REST API, so this module is provider glue
(no ComfyUI node lives here). Node files import it as `ranomany_fal_common` — see
__init__.py, which loads this once and registers it in sys.modules before the node
loop so the isolated node modules can `import` it.

Queue REST flow (https://docs.fal.ai/model-endpoints/queue):
  1. POST https://queue.fal.run/<model_id>   (input fields at top level of the body)
       → { "request_id", "status_url", "response_url", "cancel_url" }
  2. GET <status_url>  →  { "status": "IN_QUEUE" | "IN_PROGRESS" | "COMPLETED", ... }
  3. GET <response_url> once COMPLETED  →  the model output JSON

Auth is a single header: `Authorization: Key <FAL_KEY>`.

Key resolution order (resolve_key):
  1. Value passed via the node's `api_key` input
  2. FAL_KEY environment variable
  3. .env file — searched in the node dir, custom_nodes/, and ComfyUI root
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

log = logging.getLogger("FalCommon")

_QUEUE_BASE = "https://queue.fal.run"
_ENV_VAR = "FAL_KEY"

_RETRY_STATUS  = {429, 500, 502, 503, 504}
_RETRY_DELAYS  = (2, 5, 12)
_RETRY_PHRASES = ("503", "502", "504", "500", "UNAVAILABLE", "Service Unavailable", "rate_limit")

_ENV_RELATIVE_PATHS = [".", "..", "../..", "../../..", "../../../.."]


# ---------------------------------------------------------------------------
# Key / .env resolution
# ---------------------------------------------------------------------------

def _read_env_var(path: str, var_name: str) -> str:
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
                if k.strip() == var_name:
                    return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _resolve_env(var_name: str, manual_value: str = "") -> str:
    val = (manual_value or "").strip()
    if val:
        return val
    val = os.environ.get(var_name, "").strip()
    if val:
        return val
    node_dir = os.path.dirname(os.path.abspath(__file__))
    for rel in _ENV_RELATIVE_PATHS:
        val = _read_env_var(os.path.normpath(os.path.join(node_dir, rel)), var_name)
        if val:
            return val
    return ""


def resolve_key(api_key_input: str = "") -> tuple:
    """Return (key, status_badge). Empty key => ('', '❌ no key found')."""
    key = _resolve_env(_ENV_VAR, api_key_input)
    if key:
        return key, "✅ FAL_KEY found"
    return "", "❌ no FAL_KEY found"


# ---------------------------------------------------------------------------
# Media → data URIs
# ---------------------------------------------------------------------------

def image_to_data_uri(tensor: torch.Tensor) -> str:
    """A single H×W×3 (or 1×H×W×3) IMAGE tensor → PNG data URI."""
    t = tensor[0] if tensor.ndim == 4 else tensor
    arr = (t.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def video_to_data_uri(video: dict) -> str:
    """A ComfyUI VIDEO dict ({'filepath': ...}) → mp4 data URI."""
    filepath = (video or {}).get("filepath", "")
    if not filepath or not os.path.isfile(filepath):
        raise ValueError(f"[fal] video file not found: {filepath!r}")
    with open(filepath, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:video/mp4;base64,{b64}"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _http_post(url: str, body: dict, key: str) -> dict:
    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Key {key}",
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"[fal] HTTP {e.code}: {body_text}") from e


def _http_get(url: str, key: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Key {key}"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"[fal] HTTP {e.code}: {body_text}") from e


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc)
    if any(str(s) in msg for s in _RETRY_STATUS):
        return True
    return any(s in msg for s in _RETRY_PHRASES)


# ---------------------------------------------------------------------------
# Queue: submit / poll / run
# ---------------------------------------------------------------------------

def submit(model_id: str, payload: dict, key: str) -> dict:
    """POST the input to the queue. Returns {request_id, status_url, response_url, ...}."""
    url = f"{_QUEUE_BASE}/{model_id}"
    resp = _http_post(url, payload, key)
    if not resp.get("status_url") or not resp.get("response_url"):
        raise RuntimeError(f"[fal] unexpected submit response: {resp}")
    return resp


def poll(status_url: str, response_url: str, key: str,
         max_wait: int, poll_interval: int, label: str = "fal") -> dict:
    """Poll status_url until COMPLETED, then GET response_url and return the output JSON."""
    elapsed = 0
    while True:
        if elapsed >= max_wait:
            raise TimeoutError(f"[{label}] timed out after {max_wait}s. status_url={status_url}")
        time.sleep(poll_interval)
        elapsed += poll_interval
        status_resp = _http_get(status_url, key)
        status = status_resp.get("status", "UNKNOWN")
        log.info(f"[{label}] status={status} elapsed={elapsed}s")
        if status == "COMPLETED":
            result = _http_get(response_url, key)
            err = result.get("error") or result.get("detail")
            if err:
                raise RuntimeError(f"[{label}] generation failed: {err}")
            return result
        if status in ("FAILED", "ERROR", "CANCELLED"):
            raise RuntimeError(f"[{label}] task {status}: {status_resp}")


def run(model_id: str, payload: dict, key: str, max_wait: int, poll_interval: int,
        label: str = "fal", retries: int = 0) -> dict:
    """Submit (with transient-error retries) then poll to the final output JSON."""
    retries = max(0, min(int(retries), len(_RETRY_DELAYS)))
    resp = None
    for attempt in range(retries + 1):
        try:
            log.info(f"[{label}] POST {model_id}")
            resp = submit(model_id, payload, key)
            break
        except Exception as exc:
            if not _is_retryable(exc) or attempt >= retries:
                raise
            delay = _RETRY_DELAYS[attempt]
            log.warning(f"[{label}] transient error attempt {attempt+1}: {exc}; retry in {delay}s")
            time.sleep(delay)

    log.info(f"[{label}] request_id={resp.get('request_id')}, polling (max_wait={max_wait}s)…")
    return poll(resp["status_url"], resp["response_url"], key, max_wait, poll_interval, label)


# ---------------------------------------------------------------------------
# Output → VIDEO
# ---------------------------------------------------------------------------

def download_video(url: str) -> str:
    """Download a video URL to a temp .mp4 file and return its path."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        with urllib.request.urlopen(url) as r:
            tmp.write(r.read())
        return tmp.name


def result_to_video(result: dict) -> tuple:
    """fal output JSON → (VIDEO dict, seed). Downloads result['video']['url']."""
    video = (result or {}).get("video") or {}
    url = video.get("url")
    if not url:
        raise RuntimeError(f"[fal] no video.url in result: {result}")
    filepath = download_video(url)
    return {"filepath": filepath, "mime_type": "video/mp4"}, _seed_of(result)


# ---------------------------------------------------------------------------
# Output → IMAGE
# ---------------------------------------------------------------------------

def _seed_of(result: dict) -> int:
    seed = (result or {}).get("seed", -1)
    try:
        return int(seed)
    except (TypeError, ValueError):
        return -1


def image_from_url(url: str) -> torch.Tensor:
    """Download an image URL → H×W×3 float tensor in [0,1]."""
    with urllib.request.urlopen(url) as r:
        raw = r.read()
    arr = np.array(Image.open(io.BytesIO(raw)).convert("RGB")).astype(np.float32) / 255.0
    return torch.from_numpy(arr)


def _stack_batch(tensors: list) -> torch.Tensor:
    """Stack H×W×3 tensors into an N×H×W×3 batch, zero-padding to the largest size."""
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


def result_to_images(result: dict) -> tuple:
    """fal output JSON → (IMAGE batch tensor, seed). Downloads every result['images'][].url."""
    images = (result or {}).get("images") or []
    urls = [im.get("url") for im in images if im.get("url")]
    if not urls:
        raise RuntimeError(f"[fal] no images in result: {result}")
    tensors = [image_from_url(u) for u in urls]
    return _stack_batch(tensors), _seed_of(result)


# ---------------------------------------------------------------------------
# Output → IMAGE + MASK (alpha-preserving, for RGBA / layered models)
# ---------------------------------------------------------------------------

def image_from_url_rgba(url: str) -> tuple:
    """Download an image URL → (H×W×3 RGB float tensor, H×W MASK float tensor).

    Alpha is preserved as a ComfyUI MASK where 1 = transparent (0 = opaque),
    matching ComfyUI's convention. Images without alpha yield an all-zero mask.
    """
    with urllib.request.urlopen(url) as r:
        raw = r.read()
    rgba = np.array(Image.open(io.BytesIO(raw)).convert("RGBA")).astype(np.float32) / 255.0
    rgb  = torch.from_numpy(rgba[:, :, :3])       # H×W×3
    mask = torch.from_numpy(1.0 - rgba[:, :, 3])  # H×W, 1 = transparent
    return rgb, mask


def _stack_batch_with_masks(tensors: list, masks: list) -> tuple:
    """Stack H×W×3 images + H×W masks into batches, zero-padding to the largest size.

    Image padding is black; mask padding is 1 (transparent), so composited padding
    stays invisible.
    """
    if len(tensors) == 1:
        return tensors[0].unsqueeze(0), masks[0].unsqueeze(0)
    max_h = max(t.shape[0] for t in tensors)
    max_w = max(t.shape[1] for t in tensors)
    p_imgs, p_masks = [], []
    for img, mask in zip(tensors, masks):
        h, w = img.shape[:2]
        if h < max_h or w < max_w:
            pad_img = torch.zeros(max_h, max_w, 3, dtype=img.dtype)
            pad_img[:h, :w] = img
            pad_mask = torch.ones(max_h, max_w, dtype=mask.dtype)  # padding is transparent
            pad_mask[:h, :w] = mask
            img, mask = pad_img, pad_mask
        p_imgs.append(img)
        p_masks.append(mask)
    return torch.stack(p_imgs, dim=0), torch.stack(p_masks, dim=0)


def result_to_images_rgba(result: dict) -> tuple:
    """fal output JSON → (IMAGE batch, MASK batch, seed), preserving per-image alpha.

    Use for RGBA / layered endpoints (e.g. qwen-image-layered) where each output
    layer carries transparency. Downloads every result['images'][].url.
    """
    images = (result or {}).get("images") or []
    urls = [im.get("url") for im in images if im.get("url")]
    if not urls:
        raise RuntimeError(f"[fal] no images in result: {result}")
    pairs = [image_from_url_rgba(u) for u in urls]
    tensors = [rgb for rgb, _ in pairs]
    masks   = [m for _, m in pairs]
    batch, mask_batch = _stack_batch_with_masks(tensors, masks)
    return batch, mask_batch, _seed_of(result)

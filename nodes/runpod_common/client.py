"""
runpod_common — shared transport for every RunPod-serverless node in this bundle.

RunPod serverless endpoints all speak the same async REST API, so this module is
provider glue (no ComfyUI node lives here). Node files import it as
`ranomany_runpod_common` — see __init__.py, which loads this once and registers it
in sys.modules before the node loop so the isolated node modules can `import` it.

Async run REST flow (https://docs.runpod.io/serverless/endpoints/job-operations):
  1. POST https://api.runpod.ai/v2/<endpoint_id>/run   body {"input": {...}}
       → { "id": "<job_id>", "status": "IN_QUEUE" }
  2. GET  https://api.runpod.ai/v2/<endpoint_id>/status/<job_id>
       → { "status": "IN_QUEUE" | "IN_PROGRESS" | "COMPLETED" | "FAILED" |
                     "CANCELLED" | "TIMED_OUT", "output": {...} }
  3. Once COMPLETED, the worker's return value is in "output".

Auth is a single header: `Authorization: Bearer <RUNPOD_API_KEY>`.

Our workers (see workers/ in this repo) wrap their output in one envelope:
  ok:    {"status": "ok",    "result": {...}, "logs": [...]?}
  error: {"status": "error", "error": "...", "type": "validation|timeout|internal"}

Config resolution order (resolve_config), same chain as fal_common:
  1. Value passed via the node's api_key / endpoint_id input
  2. RUNPOD_API_KEY / RUNPOD_ENDPOINT_ID environment variables
  3. .env file — searched in the node dir, custom_nodes/, and ComfyUI root
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

log = logging.getLogger("RunPodCommon")

_API_BASE = "https://api.runpod.ai/v2"
_KEY_ENV_VAR = "RUNPOD_API_KEY"
_ENDPOINT_ENV_VAR = "RUNPOD_ENDPOINT_ID"

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


def resolve_config(api_key: str = "", endpoint_id: str = "") -> tuple:
    """Return (key, endpoint_id, status_badge). Missing values come back as ''."""
    key = _resolve_env(_KEY_ENV_VAR, api_key)
    endpoint = _resolve_env(_ENDPOINT_ENV_VAR, endpoint_id)
    missing = [name for name, val in
               ((_KEY_ENV_VAR, key), (_ENDPOINT_ENV_VAR, endpoint)) if not val]
    if missing:
        return key, endpoint, "❌ missing " + " + ".join(missing)
    return key, endpoint, f"✅ {_KEY_ENV_VAR} + {_ENDPOINT_ENV_VAR} found"


# ---------------------------------------------------------------------------
# IMAGE tensor ↔ base64
# ---------------------------------------------------------------------------

def image_to_b64(tensor: torch.Tensor) -> str:
    """A single H×W×3 (or 1×H×W×3) IMAGE tensor → base64-encoded PNG (no data-URI prefix)."""
    t = tensor[0] if tensor.ndim == 4 else tensor
    arr = (t.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def image_from_b64(b64: str) -> torch.Tensor:
    """Base64 image (data-URI prefix tolerated) → H×W×3 float tensor in [0,1]."""
    if "," in b64 and b64.lstrip().startswith("data:"):
        b64 = b64.split(",", 1)[1]
    raw = base64.b64decode(b64)
    arr = np.array(Image.open(io.BytesIO(raw)).convert("RGB")).astype(np.float32) / 255.0
    return torch.from_numpy(arr)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _http_post(url: str, body: dict, key: str) -> dict:
    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {key}",
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"[runpod] HTTP {e.code}: {body_text}") from e


def _http_get(url: str, key: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"[runpod] HTTP {e.code}: {body_text}") from e


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc)
    if any(str(s) in msg for s in _RETRY_STATUS):
        return True
    return any(s in msg for s in _RETRY_PHRASES)


# ---------------------------------------------------------------------------
# Queue: submit / poll / run
# ---------------------------------------------------------------------------

def submit(endpoint_id: str, key: str, payload: dict) -> str:
    """POST the input to /run. Returns the job id."""
    url = f"{_API_BASE}/{endpoint_id}/run"
    resp = _http_post(url, {"input": payload}, key)
    job_id = resp.get("id")
    if not job_id:
        raise RuntimeError(f"[runpod] unexpected submit response: {resp}")
    return job_id


def poll(endpoint_id: str, key: str, job_id: str,
         max_wait: int, poll_interval: int, label: str = "runpod") -> dict:
    """Poll /status/<job_id> until COMPLETED and return the worker's output."""
    status_url = f"{_API_BASE}/{endpoint_id}/status/{job_id}"
    elapsed = 0
    while True:
        if elapsed >= max_wait:
            raise TimeoutError(f"[{label}] timed out after {max_wait}s. job_id={job_id}")
        time.sleep(poll_interval)
        elapsed += poll_interval
        resp = _http_get(status_url, key)
        status = resp.get("status", "UNKNOWN")
        log.info(f"[{label}] status={status} elapsed={elapsed}s")
        if status == "COMPLETED":
            return resp.get("output") or {}
        if status in ("FAILED", "CANCELLED", "TIMED_OUT"):
            err = resp.get("error") or resp
            raise RuntimeError(f"[{label}] job {status}: {err}")


def run(endpoint_id: str, key: str, payload: dict, max_wait: int, poll_interval: int,
        label: str = "runpod", retries: int = 0) -> dict:
    """Submit (with transient-error retries) then poll to the worker output."""
    retries = max(0, min(int(retries), len(_RETRY_DELAYS)))
    job_id = None
    for attempt in range(retries + 1):
        try:
            log.info(f"[{label}] POST {endpoint_id}/run")
            job_id = submit(endpoint_id, key, payload)
            break
        except Exception as exc:
            if not _is_retryable(exc) or attempt >= retries:
                raise
            delay = _RETRY_DELAYS[attempt]
            log.warning(f"[{label}] transient error attempt {attempt+1}: {exc}; retry in {delay}s")
            time.sleep(delay)

    log.info(f"[{label}] job_id={job_id}, polling (max_wait={max_wait}s)…")
    return poll(endpoint_id, key, job_id, max_wait, poll_interval, label)


# ---------------------------------------------------------------------------
# Output envelope → IMAGE
# ---------------------------------------------------------------------------

def result_to_image(output: dict, label: str = "runpod") -> tuple:
    """Worker envelope → (1×H×W×3 IMAGE tensor, seed). Raises on the error envelope."""
    if not isinstance(output, dict):
        raise RuntimeError(f"[{label}] unexpected worker output: {output!r}")
    status = output.get("status")
    if status == "error":
        err_type = output.get("type", "unknown")
        raise RuntimeError(f"[{label}] worker error ({err_type}): {output.get('error')}")
    if status != "ok":
        raise RuntimeError(f"[{label}] unexpected worker output: {output}")
    result = output.get("result") or {}
    b64 = result.get("image")
    if not b64:
        raise RuntimeError(f"[{label}] no result.image in worker output: {list(result)}")
    tensor = image_from_b64(b64).unsqueeze(0)
    try:
        seed = int(result.get("seed", -1))
    except (TypeError, ValueError):
        seed = -1
    return tensor, seed

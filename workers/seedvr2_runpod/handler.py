"""
RunPod serverless worker — SeedVR2 single-image upscaling.

Wraps the standalone CLI of numz/ComfyUI-SeedVR2_VideoUpscaler (vendored into the
image at SEEDVR2_DIR, pinned commit — see Dockerfile). Instead of shelling out per
job, the handler drives the CLI's own entry points in-process:

  parse_arguments()      — synthetic sys.argv, so every default/choice comes from
                           the pinned source, with real argparse validation
  download_weight()      — HF auto-download into SEEDVR2_MODEL_DIR (put this on a
                           network volume so weights survive cold starts)
  process_single_file()  — the 4-phase encode→upscale→decode→postprocess pipeline,
                           with runner_cache so the model stays loaded across warm
                           jobs (reloaded only when the requested model changes)

Contract (matches nodes/runpod_common/client.py in Ranomany-ComfyNodes):
  input:  {mode:"upscale", image:<b64>, image_mime?, model?, resolution?,
           max_resolution?, seed?, color_correction?, debug_level?}
  ok:     {status:"ok", result:{image,<b64 png>, mime_type, width, height,
           model_used, seed, elapsed_seconds}, logs?:[...]}
  error:  {status:"error", error:"...", type:"validation|internal", logs?:[...]}

Auth is RunPod's platform Bearer key — no extra shared secret.

Env vars:
  SEEDVR2_DIR        vendored repo location        (default /app/SeedVR2)
  SEEDVR2_MODEL_DIR  weights dir                   (default /runpod-volume/models/SEEDVR2
                                                    if /runpod-volume exists, else
                                                    <SEEDVR2_DIR>/models/SEEDVR2)
"""

import base64
import io
import logging
import os
import sys
import tempfile
import time

import runpod

log = logging.getLogger("seedvr2-worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SEEDVR2_DIR = os.environ.get("SEEDVR2_DIR", "/app/SeedVR2")

# Model whitelist mirrors the pinned repo's src/utils/model_registry.py (DiT entries).
_DIT_MODELS = {
    "seedvr2_ema_3b_fp8_e4m3fn.safetensors",
    "seedvr2_ema_3b_fp16.safetensors",
    "seedvr2_ema_3b-Q8_0.gguf",
    "seedvr2_ema_3b-Q4_K_M.gguf",
    "seedvr2_ema_7b_fp8_e4m3fn_mixed_block35_fp16.safetensors",
    "seedvr2_ema_7b_fp16.safetensors",
    "seedvr2_ema_7b-Q4_K_M.gguf",
    "seedvr2_ema_7b_sharp_fp8_e4m3fn_mixed_block35_fp16.safetensors",
    "seedvr2_ema_7b_sharp_fp16.safetensors",
    "seedvr2_ema_7b_sharp-Q4_K_M.gguf",
}
_DEFAULT_MODEL = "seedvr2_ema_3b_fp8_e4m3fn.safetensors"
_COLOR_CORRECTIONS = {"lab", "wavelet", "wavelet_adaptive", "hsv", "adain", "none"}

# Warm-worker state: the vendored CLI module, its runner cache, and which model
# the cache currently holds. Cleared when a job requests a different model.
_state = {"cli": None, "runner_cache": {}, "model": None, "downloaded": set()}


def _model_dir() -> str:
    override = os.environ.get("SEEDVR2_MODEL_DIR", "").strip()
    if override:
        return override
    if os.path.isdir("/runpod-volume"):
        return "/runpod-volume/models/SEEDVR2"
    return os.path.join(SEEDVR2_DIR, "models", "SEEDVR2")


def _get_cli():
    """Import the vendored inference_cli lazily (pulls in torch/cv2 — GPU box only)."""
    if _state["cli"] is None:
        if SEEDVR2_DIR not in sys.path:
            sys.path.insert(0, SEEDVR2_DIR)
        import inference_cli  # noqa: PLC0415 — deliberate lazy heavy import
        _state["cli"] = inference_cli
    return _state["cli"]


def _run_inference(in_path: str, out_path: str, params: dict, debug: bool) -> None:
    """Upscale in_path → out_path via the vendored CLI's own pipeline."""
    cli = _get_cli()
    cli.debug.enabled = debug

    argv = [
        "inference_cli.py", in_path,
        "--output", out_path,
        "--output_format", "png",
        "--dit_model", params["model"],
        "--resolution", str(params["resolution"]),
        "--max_resolution", str(params["max_resolution"]),
        "--seed", str(params["seed"]),
        "--color_correction", params["color_correction"],
        "--batch_size", "1",
        "--model_dir", _model_dir(),
        "--cache_dit", "--cache_vae",
        "--dit_offload_device", "cpu",
        "--vae_offload_device", "cpu",
    ]
    if debug:
        argv.append("--debug")
    old_argv = sys.argv
    sys.argv = argv
    try:
        args = cli.parse_arguments()
    finally:
        sys.argv = old_argv

    if params["model"] not in _state["downloaded"]:
        if not cli.download_weight(dit_model=args.dit_model, vae_model=cli.DEFAULT_VAE,
                                   model_dir=args.model_dir, debug=cli.debug):
            raise RuntimeError(f"weight download failed for {args.dit_model}")
        _state["downloaded"].add(params["model"])

    # runner_cache keeps DiT+VAE loaded across warm jobs; drop it on model switch.
    if _state["model"] != params["model"]:
        _state["runner_cache"] = {}
        _state["model"] = params["model"]

    frames = cli.process_single_file(in_path, args, ["0"], out_path,
                                     runner_cache=_state["runner_cache"])
    if not frames or not os.path.isfile(out_path):
        raise RuntimeError(f"pipeline produced no output ({frames} frames written)")


def _decode_to_png(b64: str, path: str) -> None:
    """b64 (data-URI prefix tolerated) → normalized RGB PNG on disk."""
    from PIL import Image  # local import: keeps module importable in slim test envs
    if "," in b64 and b64.lstrip().startswith("data:"):
        b64 = b64.split(",", 1)[1]
    raw = base64.b64decode(b64, validate=True)
    img = Image.open(io.BytesIO(raw))
    img.convert("RGB").save(path, format="PNG")


def _png_response(path: str) -> dict:
    from PIL import Image
    with open(path, "rb") as f:
        raw = f.read()
    with Image.open(io.BytesIO(raw)) as img:
        width, height = img.size
    return {
        "image": base64.b64encode(raw).decode("utf-8"),
        "mime_type": "image/png",
        "width": width,
        "height": height,
    }


class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


def _error(message: str, err_type: str, logs=None) -> dict:
    out = {"status": "error", "error": message, "type": err_type}
    if logs:
        out["logs"] = logs
    return out


def _clamp_int(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


def handler(job: dict) -> dict:
    inp = job.get("input") or {}
    debug_level = _clamp_int(inp.get("debug_level", 0), 0, 0, 2)

    capture = None
    root_level = logging.getLogger().level
    if debug_level > 0:
        capture = _LogCapture()
        capture.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logging.getLogger().addHandler(capture)
        if debug_level >= 2:
            logging.getLogger().setLevel(logging.DEBUG)

    def _logs():
        return capture.lines if capture else None

    try:
        # ── validation ────────────────────────────────────────────────────
        if inp.get("mode", "upscale") != "upscale":
            return _error(f"unsupported mode {inp.get('mode')!r}; only 'upscale'",
                          "validation", _logs())
        if not inp.get("image"):
            return _error("missing required field 'image' (base64)", "validation", _logs())

        model = inp.get("model") or _DEFAULT_MODEL
        if model not in _DIT_MODELS:
            return _error(f"unknown model {model!r}; one of {sorted(_DIT_MODELS)}",
                          "validation", _logs())
        color_correction = inp.get("color_correction") or "wavelet"
        if color_correction not in _COLOR_CORRECTIONS:
            return _error(f"unknown color_correction {color_correction!r}; "
                          f"one of {sorted(_COLOR_CORRECTIONS)}", "validation", _logs())

        params = {
            "model": model,
            "resolution": _clamp_int(inp.get("resolution", 1080), 1080, 16, 15360),
            "max_resolution": _clamp_int(inp.get("max_resolution", 0), 0, 0, 30720),
            "seed": _clamp_int(inp.get("seed", 42), 42, 0, 2147483647),
            "color_correction": color_correction,
        }

        # ── decode → upscale → encode ─────────────────────────────────────
        started = time.time()
        with tempfile.TemporaryDirectory(prefix="seedvr2-") as tmp:
            in_path = os.path.join(tmp, "input.png")
            out_path = os.path.join(tmp, "output.png")
            try:
                _decode_to_png(inp["image"], in_path)
            except Exception as exc:  # bad b64 / not an image
                return _error(f"could not decode input image: {exc}", "validation", _logs())

            log.info("upscaling: model=%s resolution=%s max_resolution=%s seed=%s cc=%s",
                     params["model"], params["resolution"], params["max_resolution"],
                     params["seed"], params["color_correction"])
            _run_inference(in_path, out_path, params, debug=debug_level >= 2)
            result = _png_response(out_path)

        result.update({
            "model_used": params["model"],
            "seed": params["seed"],
            "elapsed_seconds": round(time.time() - started, 2),
        })
        out = {"status": "ok", "result": result}
        if debug_level > 0 and capture:
            out["logs"] = capture.lines
        return out

    except Exception as exc:  # noqa: BLE001 — jobs must return the error envelope
        log.exception("job failed")
        return _error(f"{type(exc).__name__}: {exc}", "internal", _logs())
    finally:
        if capture:
            logging.getLogger().removeHandler(capture)
        logging.getLogger().setLevel(root_level)


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})

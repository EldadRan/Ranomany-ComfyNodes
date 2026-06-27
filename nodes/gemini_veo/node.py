"""
GeminiVeo — ComfyUI node for Veo video generation.

Calls the Gemini / Veo API directly (google-genai SDK).
Outputs raw video bytes as a VIDEO output for wiring to a SaveVideo node.

API key resolution order:
  1. Value passed via the `api_key` input (or wired from an API Key node)
  2. GEMINI_API_KEY environment variable
  3. .env file — searched in the node dir, custom_nodes/, and ComfyUI root

Supports:
  - Text-to-video (prompt only)
  - Image-to-video (first frame anchor)
  - First + last frame anchoring
  - Veo 3.1 / Fast / Lite model variants
"""

import os
import io
import time
import tempfile
import logging

import numpy as np
from PIL import Image
import torch

log = logging.getLogger("GeminiVeo")

DEFAULT_VIDEO_MODEL = "veo-3.1-generate-preview"

VIDEO_MODELS = [
    "veo-3.1-generate-preview",
    "veo-3.1-fast-generate-preview",
    "veo-3.1-lite-generate-preview",
]

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


def _resolve_key(api_key_input: str) -> str:
    key = (api_key_input or "").strip()
    if key:
        return key
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    node_dir = os.path.dirname(os.path.abspath(__file__))
    for rel in _ENV_RELATIVE_PATHS:
        key = _read_env_file(os.path.normpath(os.path.join(node_dir, rel)))
        if key:
            return key
    return ""


def _get_client(api_key: str):
    from google import genai
    key = _resolve_key(api_key)
    if not key:
        raise EnvironmentError(
            "No Gemini API key found. Pass it via the api_key input, set "
            "GEMINI_API_KEY in your environment, or create a .env file with "
            "GEMINI_API_KEY=... in your ComfyUI root."
        )
    return genai.Client(api_key=key)


def _tensor_to_png_bytes(tensor: torch.Tensor) -> bytes:
    arr = (tensor.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
    pil = Image.fromarray(arr)
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


# VIDEO is a simple dict type carrying a temp filepath — compatible with
# our own SaveVideo node (and any other node that accepts a filepath dict).
VIDEO = "VIDEO"


class GeminiVeo:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "Describe the video you want to generate…",
                }),
                "model":            (VIDEO_MODELS, {"default": DEFAULT_VIDEO_MODEL}),
                "aspect_ratio":     (["16:9", "9:16"], {"default": "16:9"}),
                "resolution":       (["1080p", "720p", "4k"], {"default": "1080p"}),
                "duration_seconds": ("INT", {"default": 8, "min": 4, "max": 8, "step": 2}),
            },
            "optional": {
                "first_frame":     ("IMAGE",),
                "last_frame":      ("IMAGE",),
                "negative_prompt": ("STRING", {"multiline": False, "default": ""}),
                "api_key":         ("STRING", {"default": "", "password": True,
                                    "tooltip": "Leave blank to use GEMINI_API_KEY env var or .env file."}),
                "max_wait":        ("INT", {"default": 600, "min": 60, "max": 1800, "step": 30}),
                "poll_interval":   ("INT", {"default": 10,  "min": 5,  "max": 60,   "step": 5}),
            },
        }

    RETURN_TYPES  = (VIDEO,)
    RETURN_NAMES  = ("video",)
    FUNCTION      = "generate"
    CATEGORY      = "Ranomany/Gemini"
    OUTPUT_NODE   = False

    def generate(
        self,
        prompt:           str,
        model:            str = DEFAULT_VIDEO_MODEL,
        aspect_ratio:     str = "16:9",
        resolution:       str = "1080p",
        duration_seconds: int = 8,
        first_frame:      torch.Tensor = None,
        last_frame:       torch.Tensor = None,
        negative_prompt:  str = "",
        api_key:          str = "",
        max_wait:         int = 600,
        poll_interval:    int = 10,
    ):
        from google.genai import types

        if not prompt.strip() and first_frame is None:
            raise ValueError("GeminiVeo: provide a prompt and/or a first frame image.")

        client = _get_client(api_key)

        def _to_gemini_image(tensor):
            if tensor is None:
                return None
            if tensor.ndim == 4:
                tensor = tensor[0]
            return types.Image(
                image_bytes=_tensor_to_png_bytes(tensor),
                mime_type="image/png",
            )

        first_img = _to_gemini_image(first_frame)
        last_img  = _to_gemini_image(last_frame)

        video_cfg_kwargs = {
            "aspect_ratio":     aspect_ratio,
            "resolution":       resolution,
            "duration_seconds": int(duration_seconds),
        }
        if negative_prompt.strip():
            video_cfg_kwargs["negative_prompt"] = negative_prompt.strip()
        if last_img is not None:
            video_cfg_kwargs["last_frame"] = last_img

        video_config = types.GenerateVideosConfig(**video_cfg_kwargs)

        log.info(f"[GeminiVeo] submitting: model={model} res={resolution} dur={duration_seconds}s")
        operation = client.models.generate_videos(
            model=model,
            prompt=prompt.strip() or None,
            image=first_img,
            config=video_config,
        )
        log.info(f"[GeminiVeo] job submitted: {operation.name}")

        elapsed = 0
        while not operation.done:
            if elapsed >= max_wait:
                raise TimeoutError(
                    f"GeminiVeo: timed out after {max_wait}s. "
                    f"Gemini operation: {operation.name}"
                )
            time.sleep(poll_interval)
            elapsed += poll_interval
            log.info(f"[GeminiVeo] still running… {elapsed}s elapsed")
            try:
                operation = client.operations.get(operation)
            except Exception as e:
                log.warning(f"[GeminiVeo] poll error at {elapsed}s (continuing): {e}")

        if operation.response is None:
            err = getattr(operation, "error", None)
            msg = (getattr(err, "message", None) or str(err)) if err else \
                  "Generation completed with no response — likely a silent safety-filter rejection."
            raise RuntimeError(f"GeminiVeo: {msg}")

        generated = operation.response.generated_videos
        if not generated:
            raise RuntimeError("GeminiVeo: generation completed but no videos were returned.")

        gen_video   = generated[0].video
        video_bytes = getattr(gen_video, "video_bytes", None)

        if not video_bytes:
            try:
                client.files.download(file=gen_video)
                video_bytes = getattr(gen_video, "video_bytes", None)
            except Exception as e:
                log.warning(f"[GeminiVeo] files.download failed: {e}")

        if not video_bytes:
            uri = getattr(gen_video, "uri", None) or getattr(gen_video, "name", None)
            raise RuntimeError(
                f"GeminiVeo: no inline bytes returned (uri={uri!r}). "
                "SDK may require explicit file download — check google-genai version."
            )

        # Write to a temp file — SaveVideo will move it to the output directory
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        tmp.write(video_bytes)
        tmp.flush()
        tmp.close()
        log.info(f"[GeminiVeo] temp video → {tmp.name}")

        return ({"filepath": tmp.name, "mime_type": "video/mp4"},)


# ── SaveVideo node ─────────────────────────────────────────────────────────────

import folder_paths


def _embed_mp4_metadata(path: str, meta_pairs: dict):
    """Write key/value pairs as custom QuickTime atoms (readable by exiftool)."""
    try:
        from mutagen.mp4 import MP4, MP4FreeForm, AtomDataType
    except ImportError:
        log.warning("[SaveVideo] mutagen not installed — skipping metadata embed. "
                    "Run: pip install mutagen>=1.47.0")
        return
    try:
        tags = MP4(path)
        if tags.tags is None:
            tags.add_tags()
        for k, v in meta_pairs.items():
            atom = f"----:com.ranomany.comfynodes:{k}"
            tags[atom] = [MP4FreeForm(v.encode("utf-8"), dataformat=AtomDataType.UTF8)]
        tags.save()
        log.info(f"[SaveVideo] embedded {len(meta_pairs)} metadata field(s)")
    except Exception as e:
        log.warning(f"[SaveVideo] metadata embed failed: {e}")


class SaveVideo:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video":           (VIDEO,),
                "filename_prefix": ("STRING", {"default": "video"}),
            },
            "optional": {
                "extra_metadata": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": 'Optional JSON object. Each key/value is written as a custom MP4 metadata atom. '
                               'Example: {"prompt": "misty forest", "model": "veo-3.1-generate-preview"}',
                }),
            },
        }

    RETURN_TYPES  = ("STRING",)
    RETURN_NAMES  = ("filepath",)
    FUNCTION      = "save"
    CATEGORY      = "Ranomany"
    OUTPUT_NODE   = True

    def save(self, video: dict, filename_prefix: str = "video", extra_metadata: str = ""):
        import json
        import shutil

        src = video["filepath"]
        output_dir = folder_paths.get_output_directory()
        full_output_folder, filename, counter, subfolder, _ = (
            folder_paths.get_save_image_path(filename_prefix, output_dir, 1920, 1080)
        )
        file_name = f"{filename}_{counter:05}_.mp4"
        out_path  = os.path.join(full_output_folder, file_name)

        os.makedirs(full_output_folder, exist_ok=True)
        shutil.copy2(src, out_path)
        log.info(f"[SaveVideo] saved → {out_path}")

        meta_pairs: dict[str, str] = {}
        if extra_metadata.strip():
            try:
                parsed = json.loads(extra_metadata)
                if isinstance(parsed, dict):
                    meta_pairs = {str(k): str(v) for k, v in parsed.items()}
            except json.JSONDecodeError:
                meta_pairs = {"extra_metadata_raw": extra_metadata}

        if meta_pairs:
            _embed_mp4_metadata(out_path, meta_pairs)

        return {
            "ui": {
                "videos": [{"filename": file_name, "subfolder": subfolder, "type": "output"}],
            },
            "result": (out_path,),
        }


NODE_CLASS_MAPPINGS = {
    "GeminiVeo":        GeminiVeo,
    "RananomySaveVideo": SaveVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "GeminiVeo":        "Gemini Veo Generate",
    "RananomySaveVideo": "Save Video",
}

"""
GeminiVeo — ComfyUI node for Gemini Omni video generation.

Veo 3.1 Preview on the Gemini API shuts down on 2026-10-22; this node now
calls Gemini Omni Flash through the Interactions API (google-genai SDK).
The node id, name and widgets are unchanged so saved workflows keep working;
only the model dropdown differs.
Outputs raw video bytes as a VIDEO output for wiring to a SaveVideo node.

API key resolution order:
  1. Value passed via the `api_key` input (or wired from an API Key node)
  2. GEMINI_API_KEY environment variable
  3. .env file — searched in the node dir, custom_nodes/, and ComfyUI root

Supports:
  - Text-to-video (prompt only)
  - Image-to-video (first frame anchor)
  - First + last frame anchoring
"""

import os
import io
import time
import base64
import tempfile
import logging

import numpy as np
from PIL import Image
import torch

log = logging.getLogger("GeminiVeo")

DEFAULT_VIDEO_MODEL = "gemini-omni-1.1-flash"

VIDEO_MODELS = [
    "gemini-omni-1.1-flash",
]

# Veo 3.1 Preview ids saved in old workflows — accepted and run on Omni.
LEGACY_VEO_MODELS = {
    "veo-3.1-generate-preview",
    "veo-3.1-fast-generate-preview",
    "veo-3.1-lite-generate-preview",
}

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


def _tensor_to_png_bytes(tensor: torch.Tensor) -> bytes:
    arr = (tensor.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
    pil = Image.fromarray(arr)
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


def _find_video_output(interaction):
    """Return the first video content block of an interaction, or None.

    Newer SDKs expose `output_video`; older ones only have `outputs`, and the
    REST shape puts it under `steps`.
    """
    video = getattr(interaction, "output_video", None)
    if video is not None:
        return video
    blocks = list(getattr(interaction, "outputs", None) or [])
    for step in getattr(interaction, "steps", None) or []:
        blocks.extend(getattr(step, "outputs", None) or getattr(step, "content", None) or [])
    for block in blocks:
        if getattr(block, "type", None) == "video":
            return block
    return None


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
                    "placeholder": "Describe the video you want to generate, including sound…",
                }),
                "model":            (VIDEO_MODELS, {"default": DEFAULT_VIDEO_MODEL}),
                "aspect_ratio":     (["16:9", "9:16"], {"default": "16:9"}),
                "resolution":       (["1080p", "720p", "4k", "360p"], {"default": "1080p",
                                    "tooltip": "Omni generates at 720p; 1080p and 4k are upscaled."}),
                "duration_seconds": ("INT", {"default": 8, "min": 4, "max": 8, "step": 4,
                                    "tooltip": "Kept for workflow compatibility — Omni has no duration "
                                               "setting and picks the length itself."}),
            },
            "optional": {
                "first_frame":     ("IMAGE",),
                "last_frame":      ("IMAGE",),
                "negative_prompt": ("STRING", {"multiline": False, "default": "",
                                    "tooltip": "Omni has no negative-prompt parameter; this is appended to the prompt as 'Avoid: …'."}),
                "api_key":         ("STRING", {"default": "", "password": True,
                                    "tooltip": "Leave blank to use GEMINI_API_KEY env var or .env file."}),
                "max_wait":        ("INT", {"default": 1200, "min": 60, "max": 3600, "step": 30}),
                "poll_interval":   ("INT", {"default": 10,  "min": 5,  "max": 60,   "step": 5}),
            },
        }

    RETURN_TYPES  = (VIDEO, "STRING")
    RETURN_NAMES  = ("video", "key_status")
    FUNCTION      = "generate"
    CATEGORY      = "Ranomany/Gemini"
    OUTPUT_NODE   = False

    @classmethod
    def VALIDATE_INPUTS(cls, model):
        # Taking `model` here skips ComfyUI's combo check, so old workflows
        # saved with a Veo id still queue instead of failing "not in list".
        if model in VIDEO_MODELS or model in LEGACY_VEO_MODELS:
            return True
        return f"Unknown model '{model}'. Choose one of {VIDEO_MODELS}."

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
        max_wait:         int = 1200,
        poll_interval:    int = 10,
    ):
        if not prompt.strip() and first_frame is None:
            raise ValueError("GeminiVeo: provide a prompt and/or a first frame image.")
        if last_frame is not None and first_frame is None:
            raise ValueError("GeminiVeo: last_frame needs a first_frame as well.")

        if model in LEGACY_VEO_MODELS:
            log.info(f"[GeminiVeo] {model} is shut down — using {DEFAULT_VIDEO_MODEL}")
            model = DEFAULT_VIDEO_MODEL

        client, key_status = _get_client(api_key)

        def _image_part(tensor):
            if tensor.ndim == 4:
                tensor = tensor[0]
            return {
                "type": "image",
                "data": base64.b64encode(_tensor_to_png_bytes(tensor)).decode("ascii"),
                "mime_type": "image/png",
            }

        text = prompt.strip()
        if negative_prompt.strip():
            text = f"{text}\nAvoid: {negative_prompt.strip()}".strip()

        parts = [_image_part(t) for t in (first_frame, last_frame) if t is not None]
        if text:
            parts.append({"type": "text", "text": text})

        create_kwargs = {
            "model": model,
            "input": parts,
            "response_format": {
                "type": "video",
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                # Inline base64 is capped at ~4MB; a file URI handles any size.
                "delivery": "uri",
            },
            "background": False,
            "store": False,
            "timeout": float(max_wait),
        }
        if first_frame is not None:
            create_kwargs["generation_config"] = {"video_config": {"task": "image_to_video"}}

        log.info(f"[GeminiVeo] submitting: model={model} res={resolution} images={len(parts) - bool(text)}")
        start = time.monotonic()
        try:
            interaction = client.interactions.create(**create_kwargs)
        except Exception as e:
            if "timeout" in type(e).__name__.lower():
                raise TimeoutError(f"GeminiVeo: timed out after {max_wait}s.") from e
            raise RuntimeError(f"GeminiVeo: {e}") from e
        log.info(f"[GeminiVeo] interaction {interaction.id} → {interaction.status} "
                 f"in {time.monotonic() - start:.0f}s")

        if interaction.status != "completed":
            raise RuntimeError(
                f"GeminiVeo: interaction ended with status '{interaction.status}' — "
                "likely a safety-filter rejection. Re-queue or rephrase the prompt."
            )

        gen_video = _find_video_output(interaction)
        if gen_video is None:
            raise RuntimeError("GeminiVeo: generation completed but no video was returned.")

        video_bytes = None
        data = getattr(gen_video, "data", None)
        if data:
            video_bytes = base64.b64decode(data)
        elif getattr(gen_video, "uri", None):
            video_bytes = self._download(client, gen_video.uri,
                                         max_wait - (time.monotonic() - start), poll_interval)

        if not video_bytes:
            raise RuntimeError(
                f"GeminiVeo: no video bytes returned (uri={getattr(gen_video, 'uri', None)!r})."
            )

        # Write to a temp file — SaveVideo will move it to the output directory
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        tmp.write(video_bytes)
        tmp.flush()
        tmp.close()
        log.info(f"[GeminiVeo] temp video → {tmp.name}")

        return ({"filepath": tmp.name, "mime_type": "video/mp4"}, key_status)

    @staticmethod
    def _download(client, uri: str, remaining: float, poll_interval: int) -> bytes:
        """Wait for the output file to become ACTIVE, then download it."""
        name = f"files/{uri.rstrip('/').split('/')[-1]}"
        deadline = time.monotonic() + max(remaining, 30)
        while True:
            state = getattr(client.files.get(name=name).state, "name", "")
            if state == "ACTIVE":
                break
            if state == "FAILED":
                raise RuntimeError(f"GeminiVeo: output file {name} failed processing.")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"GeminiVeo: output file {name} not ready in time.")
            time.sleep(poll_interval)
        return client.files.download(file=uri)


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
                               'Example: {"prompt": "misty forest", "model": "gemini-omni-1.1-flash"}',
                }),
            },
        }

    RETURN_TYPES  = ("STRING",)
    RETURN_NAMES  = ("filepath",)
    FUNCTION      = "save"
    CATEGORY      = "Ranomany/Utils"
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
                "gifs": [{"filename": file_name, "subfolder": subfolder,
                           "type": "output", "format": "video/mp4"}],
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

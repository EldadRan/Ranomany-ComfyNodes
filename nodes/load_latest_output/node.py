"""
LoadImageEdit ("Load Image (from Outputs)") — a Load Image node sourced from the
output folder. Behaves like the native LoadImage (the user can pick any output
image and the preview follows the selection), but a companion JS extension
auto-selects the newest output image whenever a workflow run finishes, so the
node is primed with the last generated image.

The image widget is a plain, frontend-recognized `image_upload` combo (NO remote
config) — that is what makes the inline image preview render in ComfyUI's
app/run panel, not just the graph editor.
"""

import os

import numpy as np
import torch
from PIL import Image, ImageOps

import folder_paths

_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _list_output_images() -> list[str]:
    """Output-folder images as combo values, annotated `name [output]`.

    The `[output]` annotation is required so the frontend's image preview and
    /view request resolve against the OUTPUT folder; without it the preview
    looks in `input/` and fails with "Image does not exist".
    """
    output_dir = folder_paths.get_output_directory()
    if not os.path.isdir(output_dir):
        return [""]
    files = []
    for root, _, fnames in os.walk(output_dir):
        for f in fnames:
            if os.path.splitext(f)[1].lower() in _EXTS:
                rel = os.path.relpath(os.path.join(root, f), output_dir)
                files.append(rel)
    files.sort()
    return [f"{rel} [output]" for rel in files] or [""]


def _find_latest(folder: str) -> str | None:
    """Newest image file under `folder` by modification time (full path)."""
    best_path = None
    best_mtime = -1.0
    for root, _, files in os.walk(folder):
        for fname in files:
            if os.path.splitext(fname)[1].lower() not in _EXTS:
                continue
            full = os.path.join(root, fname)
            try:
                mt = os.path.getmtime(full)
            except OSError:
                continue
            if mt > best_mtime:
                best_mtime = mt
                best_path = full
    return best_path


def _resolve_output_path(value: str) -> str | None:
    """Resolve a combo value to a real path inside the output directory.

    Handles a trailing ` [output]`/`[input]` annotation that the frontend may add,
    and falls back to the newest output file when the value is empty or missing.
    """
    output_dir = folder_paths.get_output_directory()
    name = (value or "").strip()
    # strip a "name [output]" style annotation if present
    if name.endswith("]") and "[" in name:
        name = name[: name.rfind("[")].strip()

    if name:
        candidate = os.path.normpath(os.path.join(output_dir, name))
        # keep the path inside the output directory
        if candidate.startswith(os.path.normpath(output_dir)) and os.path.isfile(candidate):
            return candidate

    return _find_latest(output_dir)


def _load_image(path: str):
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)

    if img.mode == "RGBA":
        rgb = img.convert("RGB")
        alpha = np.array(img)[:, :, 3].astype(np.float32) / 255.0
        mask = torch.from_numpy(1.0 - alpha).unsqueeze(0)
    else:
        rgb = img.convert("RGB")
        h, w = rgb.size[1], rgb.size[0]
        mask = torch.zeros(1, h, w, dtype=torch.float32)

    arr = np.array(rgb).astype(np.float32) / 255.0
    tensor = torch.from_numpy(arr).unsqueeze(0)  # 1×H×W×3
    return tensor, mask


class LoadImageEdit:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # Plain recognized image-upload combo over the output folder.
                # No `remote` config — that is what enables the app-mode preview.
                "image": (_list_output_images(), {
                    "image_upload": True,
                    "image_folder": "output",
                }),
            }
        }

    RETURN_TYPES  = ("IMAGE", "MASK")
    RETURN_NAMES  = ("image", "mask")
    FUNCTION      = "load"
    CATEGORY      = "Ranomany/Utils"

    @classmethod
    def IS_CHANGED(cls, image):
        path = _resolve_output_path(image)
        if path is None:
            return float("nan")
        try:
            return f"{path}:{os.path.getmtime(path)}"
        except OSError:
            return float("nan")

    def load(self, image: str):
        path = _resolve_output_path(image)
        if path is None:
            raise RuntimeError(
                "LoadImageEdit: no image files found in the output directory."
            )
        return _load_image(path)


NODE_CLASS_MAPPINGS = {
    "RanomanyLoadImageEdit": LoadImageEdit,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RanomanyLoadImageEdit": "Load Image (from Outputs)",
}

"""
LoadLatestOutput — ComfyUI node that loads either:
  • the most recently saved image from the output directory (default), or
  • a manually chosen image from the input folder (like standard LoadImage).

Outputs IMAGE + MASK with an in-node preview.
"""

import hashlib
import os

import numpy as np
import torch
from PIL import Image, ImageOps

import folder_paths

_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _list_input_images() -> list[str]:
    input_dir = folder_paths.get_input_directory()
    if not os.path.isdir(input_dir):
        return [""]
    files = sorted(
        f for f in os.listdir(input_dir)
        if os.path.splitext(f)[1].lower() in _EXTS
    )
    return files or [""]


def _resolve_input_path(image: str) -> str:
    try:
        return folder_paths.get_annotated_filepath(image)
    except Exception:
        return os.path.join(folder_paths.get_input_directory(), image)


def _find_latest(folder: str) -> str | None:
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


def _load_image(path: str):
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)

    if img.mode == "RGBA":
        rgb = img.convert("RGB")
        alpha = np.array(img)[:, :, 3].astype(np.float32) / 255.0
        mask = torch.from_numpy(1.0 - alpha).unsqueeze(0)  # 1×H×W
    else:
        rgb = img.convert("RGB")
        h, w = rgb.size[1], rgb.size[0]
        mask = torch.zeros(1, h, w, dtype=torch.float32)

    arr = np.array(rgb).astype(np.float32) / 255.0
    tensor = torch.from_numpy(arr).unsqueeze(0)  # 1×H×W×3
    return tensor, mask


class LoadLatestOutput:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "source": (["latest output", "pick image"], {"default": "latest output"}),
                "image":  (_list_input_images(), {"image_upload": True}),
            },
        }

    RETURN_TYPES  = ("IMAGE", "MASK")
    RETURN_NAMES  = ("image", "mask")
    FUNCTION      = "load"
    CATEGORY      = "Ranomany/Utils"
    OUTPUT_NODE   = True

    @classmethod
    def IS_CHANGED(cls, source, image):
        if source == "latest output":
            return float("nan")
        image_path = _resolve_input_path(image)
        m = hashlib.sha256()
        try:
            with open(image_path, "rb") as f:
                m.update(f.read())
        except OSError:
            return float("nan")
        return m.digest().hex()

    def load(self, source: str, image: str):
        if source == "latest output":
            output_dir = folder_paths.get_output_directory()
            path = _find_latest(output_dir)
            if path is None:
                raise RuntimeError(
                    "LoadLatestOutput: no image files found in the output directory."
                )
            tensor, mask = _load_image(path)
            rel = os.path.relpath(path, output_dir)
            ui_image = {
                "filename": os.path.basename(rel),
                "subfolder": os.path.dirname(rel),
                "type": "output",
            }
        else:
            path = _resolve_input_path(image)
            tensor, mask = _load_image(path)
            input_dir = folder_paths.get_input_directory()
            rel = os.path.relpath(path, input_dir)
            ui_image = {
                "filename": os.path.basename(rel),
                "subfolder": os.path.dirname(rel),
                "type": "input",
            }

        return {
            "ui": {"images": [ui_image]},
            "result": (tensor, mask),
        }


NODE_CLASS_MAPPINGS = {
    "RanomanyLoadLatestOutput": LoadLatestOutput,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RanomanyLoadLatestOutput": "Load Image Edit",
}

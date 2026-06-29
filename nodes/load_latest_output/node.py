"""
LoadImageEdit — looks and feels like the built-in Load Image node but on every
workflow execution it automatically loads the newest image from the output folder.

The image picker widget is present for visual parity; its value is ignored at
runtime — the node always returns the latest generated file.
"""

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
                "image": (_list_input_images(), {"image_upload": True}),
            },
        }

    RETURN_TYPES  = ("IMAGE", "MASK")
    RETURN_NAMES  = ("image", "mask")
    FUNCTION      = "load"
    CATEGORY      = "Ranomany/Utils"
    OUTPUT_NODE   = True

    @classmethod
    def IS_CHANGED(cls, image):
        return float("nan")

    def load(self, image: str):
        output_dir = folder_paths.get_output_directory()
        path = _find_latest(output_dir)

        if path is None:
            raise RuntimeError(
                "LoadImageEdit: no image files found in the output directory."
            )

        tensor, mask = _load_image(path)

        rel = os.path.relpath(path, output_dir)
        ui_image = {
            "filename": os.path.basename(rel),
            "subfolder": os.path.dirname(rel),
            "type": "output",
        }

        return {
            "ui": {"images": [ui_image]},
            "result": (tensor, mask),
        }


NODE_CLASS_MAPPINGS = {
    "RanomanyLoadImageEdit": LoadImageEdit,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RanomanyLoadImageEdit": "Load Image Edit",
}

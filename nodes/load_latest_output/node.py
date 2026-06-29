"""
LoadImageEdit — loads and returns the newest image from the output folder on
every workflow run. Picker widget lists output-folder images and auto-refreshes
after each run, selecting the newest file via `control_after_refresh: "first"`.
"""

import os

import numpy as np
import torch
from PIL import Image, ImageOps

import folder_paths

_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _list_output_images() -> list[str]:
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
                "image": (_list_output_images(), {
                    "image_upload": True,
                    "image_folder": "output",
                    "remote": {
                        "route": "/internal/files/output",
                        "refresh_button": True,
                        "control_after_refresh": "first",
                    },
                }),
            }
        }

    RETURN_TYPES  = ("IMAGE", "MASK")
    RETURN_NAMES  = ("image", "mask")
    FUNCTION      = "load"
    CATEGORY      = "Ranomany/Utils"

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

        return _load_image(path)


NODE_CLASS_MAPPINGS = {
    "RanomanyLoadImageEdit": LoadImageEdit,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RanomanyLoadImageEdit": "Load Image Edit",
}

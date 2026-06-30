"""
LoadImageEdit ("Load Image (Edit Mode)") — a Load Image node that uses the native
ComfyUI image picker (`image_upload`), which renders the All / Imported / Generated
asset browser with an upload button. The user can pick an input image, a generated
(output) image, or upload one; the node loads it and outputs IMAGE/MASK.

A companion JS extension (web/load_image_from_output.js) renders an <img> DOM-widget
preview that shows in BOTH the editor and the app/run panel — the native inline
preview is hardcoded to node.type === "LoadImage", so a custom node needs its own.
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
        return []
    files = [
        f for f in os.listdir(input_dir)
        if os.path.isfile(os.path.join(input_dir, f))
        and os.path.splitext(f)[1].lower() in _EXTS
    ]
    return sorted(files)


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
                # Native image picker: All / Imported / Generated browser + upload.
                "image": (_list_input_images(), {"image_upload": True}),
            }
        }

    RETURN_TYPES  = ("IMAGE", "MASK")
    RETURN_NAMES  = ("image", "mask")
    FUNCTION      = "load"
    CATEGORY      = "Ranomany/Utils"

    @classmethod
    def IS_CHANGED(cls, image):
        try:
            path = folder_paths.get_annotated_filepath(image)
            return f"{path}:{os.path.getmtime(path)}"
        except Exception:
            return float("nan")

    @classmethod
    def VALIDATE_INPUTS(cls, image):
        if not folder_paths.exists_annotated_filepath(image):
            return f"Invalid image file: {image}"
        return True

    def load(self, image: str):
        path = folder_paths.get_annotated_filepath(image)
        return _load_image(path)


NODE_CLASS_MAPPINGS = {
    "RanomanyLoadImageEdit": LoadImageEdit,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RanomanyLoadImageEdit": "Load Image (Edit Mode)",
}

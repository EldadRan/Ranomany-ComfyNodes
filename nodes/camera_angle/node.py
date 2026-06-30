"""
Ranomany Camera Angle — a port of ComfyUI-qwenmultiangle's 3D camera control.

The 3D GUI (web/camera_angle.bundle.js, Three.js baked in) drives the
horizontal_angle / vertical_angle / zoom widgets and reads the preview_images
UI output to show the input image inside the scene. This node
keeps those exact widget names so the unmodified bundle attaches to it, and
changes only the two things we care about: a finer taxonomy ("more steps") and
a Gemini-friendly prose prompt.
"""

import os
import random

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


class CameraAngle:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # Names/ranges must match web/camera_angle.bundle.js so the 3D GUI binds.
                "horizontal_angle": ("INT",   {"default": 0,   "min": 0,   "max": 360, "step": 1, "display": "slider"}),
                "vertical_angle":   ("INT",   {"default": 0,   "min": -30, "max": 60,  "step": 1, "display": "slider"}),
                "zoom":             ("FLOAT", {"default": 5.0, "min": 0.0, "max": 10.0,"step": 0.1,"display": "slider"}),
            },
            "optional": {
                "image": ("IMAGE",),
            },
        }

    RETURN_TYPES  = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES  = ("prompt", "horizontal", "vertical", "shot_size")
    FUNCTION      = "generate"
    CATEGORY      = "Ranomany/Utils"
    OUTPUT_NODE   = True

    def generate(self, horizontal_angle, vertical_angle, zoom, image=None):
        horizontal_angle = max(0, min(360, int(horizontal_angle)))
        vertical_angle   = max(-30, min(60, int(vertical_angle)))
        zoom             = max(0.0, min(10.0, float(zoom)))

        h = self._horizontal(horizontal_angle)
        v = self._vertical(vertical_angle)
        s = self._shot_size(zoom)
        prompt = (
            f"Change the camera to a {s} from a {v}, {h} of the same subject. "
            f"Preserve identity, materials, and lighting — only change the camera angle and framing."
        )

        preview_images = self._save_preview(image) if image is not None else []
        return {
            "ui": {"preview_images": preview_images},
            "result": (prompt, h, v, s),
        }

    # --- taxonomy --------------------------------------------------------

    @staticmethod
    def _horizontal(az):
        az = az % 360
        if az < 22.5 or az >= 337.5:  return "front view"
        if az < 67.5:                  return "front-right three-quarter angle"
        if az < 112.5:                 return "right side profile"
        if az < 157.5:                 return "rear-right three-quarter angle"
        if az < 202.5:                 return "rear view"
        if az < 247.5:                 return "rear-left three-quarter angle"
        if az < 292.5:                 return "left side profile"
        return                                "front-left three-quarter angle"

    @staticmethod
    def _vertical(el):
        # Reachable GUI range is -30..+60, mapped into 6 zones.
        if el < -18: return "low-angle shot"
        if el < -6:  return "slight low angle"
        if el <= 6:  return "eye-level shot"
        if el <= 20: return "slight high angle"
        if el <= 40: return "high-angle shot"
        return            "overhead high-angle shot"

    @staticmethod
    def _shot_size(d):
        # zoom: higher value = closer.
        if d < 1.5: return "extreme wide shot"
        if d < 2.4: return "wide shot"
        if d < 3.6: return "full shot"
        if d < 4.8: return "medium long shot"
        if d < 6.0: return "medium shot"
        if d < 7.5: return "close-up"
        if d < 9.5: return "extreme close-up"
        return             "macro shot"

    # --- image preview for the 3D scene ----------------------------------

    @staticmethod
    def _save_preview(image):
        """Save the first frame to the temp folder so the 3D GUI can display it.
        Returns the {filename, subfolder, type} shape the bundle expects."""
        try:
            out_dir = folder_paths.get_temp_directory()
            os.makedirs(out_dir, exist_ok=True)
            arr = (image[0].cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
            fname = f"ranomany_camera_{random.randint(0, 0xffffffff):08x}.png"
            Image.fromarray(arr).save(os.path.join(out_dir, fname), compress_level=1)
            return [{"filename": fname, "subfolder": "", "type": "temp"}]
        except Exception as e:
            print(f"[Ranomany CameraAngle] preview save failed: {e}")
            return []


class CameraAngleEdit(CameraAngle):
    """Camera Angle + built-in image picker (no IMAGE input port).

    Loads its own image via the native picker and shows it in the 3D scene
    immediately (web/camera_angle.bundle.js wires the picker -> scene), and
    outputs the loaded IMAGE/MASK alongside the camera prompt.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # Must match web/camera_angle.bundle.js so the 3D GUI binds.
                "horizontal_angle": ("INT",   {"default": 0,   "min": 0,   "max": 360, "step": 1, "display": "slider"}),
                "vertical_angle":   ("INT",   {"default": 0,   "min": -30, "max": 60,  "step": 1, "display": "slider"}),
                "zoom":             ("FLOAT", {"default": 5.0, "min": 0.0, "max": 10.0,"step": 0.1,"display": "slider"}),
                # Native image picker: All / Imported / Generated browser + upload.
                "image":            (_list_input_images(), {"image_upload": True}),
            }
        }

    RETURN_TYPES  = ("STRING", "STRING", "STRING", "STRING", "IMAGE", "MASK")
    RETURN_NAMES  = ("prompt", "horizontal", "vertical", "shot_size", "image", "mask")
    FUNCTION      = "generate"
    CATEGORY      = "Ranomany/Utils"
    OUTPUT_NODE   = False

    @classmethod
    def VALIDATE_INPUTS(cls, image, **kwargs):
        if not folder_paths.exists_annotated_filepath(image):
            return f"Invalid image file: {image}"
        return True

    def generate(self, horizontal_angle, vertical_angle, zoom, image):
        horizontal_angle = max(0, min(360, int(horizontal_angle)))
        vertical_angle   = max(-30, min(60, int(vertical_angle)))
        zoom             = max(0.0, min(10.0, float(zoom)))

        h = self._horizontal(horizontal_angle)
        v = self._vertical(vertical_angle)
        s = self._shot_size(zoom)
        prompt = (
            f"Change the camera to a {s} from a {v}, {h} of the same subject. "
            f"Preserve identity, materials, and lighting — only change the camera angle and framing."
        )

        path = folder_paths.get_annotated_filepath(image)
        img, mask = _load_image(path)
        return (prompt, h, v, s, img, mask)


NODE_CLASS_MAPPINGS = {
    "RananomyCameraAngle":     CameraAngle,
    "RanomanyCameraAngleEdit": CameraAngleEdit,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "RananomyCameraAngle":     "Camera Angle",
    "RanomanyCameraAngleEdit": "Camera Angle (Load Image)",
}

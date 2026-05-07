"""
SaveImageNoMeta — saves PNGs without ComfyUI's default workflow JSON in metadata.

ComfyUI core's SaveImage embeds the entire workflow + prompt as PNG tEXt chunks.
That leaks workflow structure to anyone who downloads the image and bloats output.
This node writes clean PNGs and embeds ONLY the keys you pass via `extra_metadata`
(a JSON object). Pass an empty string or "{}" for fully clean output.

Used by Flux2x to embed seed + model_used + workflow name and nothing else.
"""

import json
import os

import numpy as np
from PIL import Image, PngImagePlugin

import folder_paths


class SaveImageNoMeta:
    def __init__(self) -> None:
        self.output_dir = folder_paths.get_output_directory()
        self.type       = "output"
        self.compress_level = 4

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images":          ("IMAGE",),
                "filename_prefix": ("STRING", {"default": "ComfyUI"}),
            },
            "optional": {
                "extra_metadata":  ("STRING", {"default": "", "multiline": True}),
            },
        }

    RETURN_TYPES = ()
    FUNCTION     = "save"
    OUTPUT_NODE  = True
    CATEGORY     = "image/save"

    def save(self, images, filename_prefix: str = "ComfyUI",
             extra_metadata: str = "", prompt=None, extra_pnginfo=None):
        # Resolve filename pattern (handles %date% etc. via folder_paths helpers).
        full_output_folder, filename, counter, subfolder, _ = (
            folder_paths.get_save_image_path(filename_prefix, self.output_dir,
                                             images[0].shape[1], images[0].shape[0])
        )

        # Parse extra_metadata into a dict of str -> str.
        meta_pairs: dict[str, str] = {}
        if extra_metadata:
            try:
                parsed = json.loads(extra_metadata)
                if isinstance(parsed, dict):
                    for k, v in parsed.items():
                        meta_pairs[str(k)] = str(v)
            except json.JSONDecodeError:
                # Non-JSON: dump it under a single key so the user notices.
                meta_pairs["extra_metadata_raw"] = extra_metadata

        # Build the PngInfo with ONLY the explicit pairs. We deliberately do NOT
        # embed `prompt` or `extra_pnginfo` (which is where ComfyUI core puts
        # the workflow JSON) — that's the entire point of this node.
        results = []
        for batch_index, image_tensor in enumerate(images):
            arr = 255.0 * image_tensor.cpu().numpy()
            img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

            png_info = PngImagePlugin.PngInfo()
            for k, v in meta_pairs.items():
                png_info.add_text(k, v)

            file_name = f"{filename}_{counter:05}_.png"
            img.save(os.path.join(full_output_folder, file_name),
                     pnginfo=png_info, compress_level=self.compress_level)
            results.append({"filename": file_name, "subfolder": subfolder, "type": self.type})
            counter += 1

        return {"ui": {"images": results}}


NODE_CLASS_MAPPINGS = {
    "SaveImageNoMeta": SaveImageNoMeta,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SaveImageNoMeta": "Save Image (no workflow metadata)",
}

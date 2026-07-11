"""Compare Images (RGBA) — the native ComfyUI ImageCompare node, extended to
preserve alpha.

The stock ImageCompare (comfy_extras/nodes_image_compare.py) saves both sides
through PreviewImage, which flattens an IMAGE (H,W,3) to an opaque RGB PNG — so a
transparent subject (e.g. the RGBA output of our SeedVR2 upscale node) shows up
against a solid background in the slider. This node reuses that exact code path;
the only addition is an optional MASK per side. When a mask is present we fold it
into the image as a 4th (alpha) channel and hand the RGBA tensor straight to the
unmodified PreviewImage.save_images — PIL's Image.fromarray infers mode "RGBA"
from the 4-channel array and writes real transparency, so the slider composites
the two images over the canvas checkerboard just like any other RGBA preview.

Frontend (web/image_compare_rgba.js) re-binds the native `imagecompare` slider
widget to this node's class — same handler the core Comfy.ImageCompare extension
uses, just keyed to our comfyClass.

MASK convention (matches runpod_common / fal_common): 1 = transparent, so
alpha = 1 - mask.
"""


def _merge_alpha(image, mask):
    """image: (B,H,W,3) IMAGE, mask: (B,H,W) MASK → (B,H,W,4) RGBA. mask None → image unchanged."""
    if mask is None:
        return image

    import torch
    import torch.nn.functional as F

    if mask.dim() == 2:
        mask = mask.unsqueeze(0)  # (H,W) → (1,H,W)

    b, h, w, _ = image.shape

    m = mask
    if m.shape[0] == 1 and b > 1:
        m = m.repeat(b, 1, 1)
    elif m.shape[0] != b:
        n = min(m.shape[0], b)
        m, image = m[:n], image[:n]
        b = n

    if m.shape[1] != h or m.shape[2] != w:
        m = F.interpolate(m.unsqueeze(1), size=(h, w), mode="bilinear", align_corners=False).squeeze(1)

    alpha = (1.0 - m).clamp(0.0, 1.0).unsqueeze(-1)  # (B,H,W,1)
    return torch.cat([image, alpha], dim=-1)


class RanomanyImageCompareRGBA:
    """Compares two images side by side with a slider, preserving alpha (RGBA)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "optional": {
                "image_a": ("IMAGE",),
                "image_b": ("IMAGE",),
                # Optional alpha per side (1 = transparent). When wired, the side is
                # previewed as RGBA so transparency shows in the slider.
                "mask_a": ("MASK",),
                "mask_b": ("MASK",),
                # UI-only slider widget (serialize:false on the frontend, hence optional
                # so classic input validation doesn't demand a value).
                "compare_view": ("IMAGECOMPARE",),
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "compare"
    OUTPUT_NODE = True
    CATEGORY = "Ranomany/image"
    DESCRIPTION = (
        "Compare two images side by side with a draggable slider (like the native "
        "Compare Images), preserving RGBA transparency via an optional mask per side."
    )

    def compare(self, image_a=None, image_b=None, mask_a=None, mask_b=None, compare_view=None):
        import nodes  # ComfyUI core; resolved from sys.modules at runtime

        preview = nodes.PreviewImage()
        result = {"a_images": [], "b_images": []}

        if image_a is not None and len(image_a) > 0:
            saved = preview.save_images(_merge_alpha(image_a, mask_a), "comfy.compare.a")
            result["a_images"] = saved["ui"]["images"]

        if image_b is not None and len(image_b) > 0:
            saved = preview.save_images(_merge_alpha(image_b, mask_b), "comfy.compare.b")
            result["b_images"] = saved["ui"]["images"]

        return {"ui": result}


NODE_CLASS_MAPPINGS = {"RanomanyImageCompareRGBA": RanomanyImageCompareRGBA}
NODE_DISPLAY_NAME_MAPPINGS = {"RanomanyImageCompareRGBA": "Compare Images (RGBA)"}

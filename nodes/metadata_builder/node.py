"""
BuildMetadata ("Build Metadata (Text)") — compile key/value metadata into a JSON string.

YAGNI: Save Image (SaveImageNoMeta) and Save Video (SaveVideo) already embed an
`extra_metadata` JSON into the output file (PNG tEXt / MP4 atoms). This node just compiles the
data — arbitrary custom pairs plus the Cloudflare identity (email / user) — into that JSON
string, which you wire straight into either node's `extra_metadata` input. No new save logic.

Example: extra_pairs = {"Delivered by": "Ranomaly"}, email wired from Cloudflare Access
Identity → output {"Delivered by": "Ranomaly", "email": "you@x.com", "user": "you"}.
"""

import json
import logging

log = logging.getLogger("BuildMetadata")


class BuildMetadata:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "extra_pairs": ("STRING", {
                    "default": '{"Delivered by": "Ranomaly"}',
                    "multiline": True,
                    "tooltip": "JSON object of arbitrary key/value pairs to embed.",
                }),
            },
            "optional": {
                # Wire these from the Cloudflare Access Identity node (or leave unconnected).
                "email": ("STRING", {"default": "", "forceInput": True}),
                "user":  ("STRING", {"default": "", "forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("metadata_json",)
    FUNCTION     = "build"
    CATEGORY     = "Ranomany/Utils"

    def build(self, extra_pairs: str = "", email: str = "", user: str = ""):
        data: dict = {}

        s = (extra_pairs or "").strip()
        if s:
            try:
                parsed = json.loads(s)
                if isinstance(parsed, dict):
                    data = dict(parsed)
                else:
                    data = {"metadata": parsed}
            except json.JSONDecodeError:
                log.warning("[BuildMetadata] extra_pairs is not valid JSON; embedding as raw text.")
                data = {"metadata": s}

        if email:
            data["email"] = email
        if user:
            data["user"] = user

        return (json.dumps(data, ensure_ascii=False),)


NODE_CLASS_MAPPINGS = {
    "RanomanyBuildMetadata": BuildMetadata,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RanomanyBuildMetadata": "Build Metadata (Text)",
}

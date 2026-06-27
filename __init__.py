import sys
import os

# Ensure this package's directory is on sys.path so sub-packages resolve correctly
# regardless of how ComfyUI's importlib loader sets up the package context.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from nodes.gemini_api_key.node import NODE_CLASS_MAPPINGS as _km1, NODE_DISPLAY_NAME_MAPPINGS as _dn1
from nodes.gemini_image.node import NODE_CLASS_MAPPINGS as _km2, NODE_DISPLAY_NAME_MAPPINGS as _dn2
from nodes.gemini_veo.node import NODE_CLASS_MAPPINGS as _km3, NODE_DISPLAY_NAME_MAPPINGS as _dn3
from nodes.save_image_no_meta.node import NODE_CLASS_MAPPINGS as _km4, NODE_DISPLAY_NAME_MAPPINGS as _dn4

NODE_CLASS_MAPPINGS = {**_km1, **_km2, **_km3, **_km4}
NODE_DISPLAY_NAME_MAPPINGS = {**_dn1, **_dn2, **_dn3, **_dn4}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

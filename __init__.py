import importlib.util
import os

_here = os.path.dirname(os.path.abspath(__file__))


def _load(rel_path: str):
    """Load a node.py by file path, avoiding sys.modules name conflicts."""
    abs_path = os.path.join(_here, rel_path)
    # Give each module a unique internal name so they don't collide with each other
    # or with any existing sys.modules entries.
    mod_name = "_ranomany_" + rel_path.replace(os.sep, "_").replace("/", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(mod_name, abs_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_m1 = _load("nodes/gemini_api_key/node.py")
_m2 = _load("nodes/gemini_image/node.py")
_m3 = _load("nodes/gemini_veo/node.py")
_m4 = _load("nodes/save_image_no_meta/node.py")

NODE_CLASS_MAPPINGS = {
    **_m1.NODE_CLASS_MAPPINGS,
    **_m2.NODE_CLASS_MAPPINGS,
    **_m3.NODE_CLASS_MAPPINGS,
    **_m4.NODE_CLASS_MAPPINGS,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    **_m1.NODE_DISPLAY_NAME_MAPPINGS,
    **_m2.NODE_DISPLAY_NAME_MAPPINGS,
    **_m3.NODE_DISPLAY_NAME_MAPPINGS,
    **_m4.NODE_DISPLAY_NAME_MAPPINGS,
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

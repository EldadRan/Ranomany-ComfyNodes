import importlib.util
import os
import traceback

_here = os.path.dirname(os.path.abspath(__file__))

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}


def _load(rel_path: str):
    abs_path = os.path.join(_here, rel_path)
    mod_name = "_ranomany_" + rel_path.replace(os.sep, "_").replace("/", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(mod_name, abs_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_NODE_FILES = [
    ("nodes/gemini_api_key/node.py",    "gemini_api_key"),
    ("nodes/gemini_image/node.py",      "gemini_image"),
    ("nodes/gemini_veo/node.py",        "gemini_veo"),
    ("nodes/save_image_no_meta/node.py","save_image_no_meta"),
]

for _rel, _label in _NODE_FILES:
    try:
        _mod = _load(_rel)
        _km  = getattr(_mod, "NODE_CLASS_MAPPINGS", {})
        _dn  = getattr(_mod, "NODE_DISPLAY_NAME_MAPPINGS", {})
        NODE_CLASS_MAPPINGS.update(_km)
        NODE_DISPLAY_NAME_MAPPINGS.update(_dn)
        print(f"[Ranomany-ComfyNodes] OK  {_label}: {list(_km.keys())}")
    except Exception:
        print(f"[Ranomany-ComfyNodes] ERR {_label}:\n{traceback.format_exc()}")

print(f"[Ranomany-ComfyNodes] Registered nodes: {list(NODE_CLASS_MAPPINGS.keys())}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

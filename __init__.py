import importlib.util
import os
import sys
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


# Shared provider clients — loaded once and registered under a stable import name so the
# isolated node modules (execd via _load) can `import` them. Must run before the node loop.
try:
    sys.modules["ranomany_fal_common"] = _load("nodes/fal_common/client.py")
    print("[Ranomany-ComfyNodes] OK  fal_common (shared fal.ai client)")
except Exception:
    print(f"[Ranomany-ComfyNodes] ERR fal_common:\n{traceback.format_exc()}")

try:
    sys.modules["ranomany_runpod_common"] = _load("nodes/runpod_common/client.py")
    print("[Ranomany-ComfyNodes] OK  runpod_common (shared RunPod client)")
except Exception:
    print(f"[Ranomany-ComfyNodes] ERR runpod_common:\n{traceback.format_exc()}")


_NODE_FILES = [
    ("nodes/api_key/node.py",            "api_key"),
    ("nodes/gemini_image/node.py",       "gemini_image"),
    ("nodes/gemini_describe/node.py",    "gemini_describe"),
    ("nodes/gemini_veo/node.py",         "gemini_veo"),
    ("nodes/openai_image/node.py",       "openai_image"),
    ("nodes/save_image_no_meta/node.py", "save_image_no_meta"),
    ("nodes/wan_image/node.py",          "wan_image"),
    ("nodes/wan_video/node.py",          "wan_video"),
    ("nodes/load_latest_output/node.py", "load_latest_output"),
    ("nodes/camera_angle/node.py",       "camera_angle"),
    ("nodes/video_info/node.py",         "video_info"),
    ("nodes/cf_identity/node.py",        "cf_identity"),
    ("nodes/metadata_builder/node.py",   "metadata_builder"),
    ("nodes/multi_concat/node.py",       "multi_concat"),
    ("nodes/wan_fal/node.py",            "wan_fal"),
    ("nodes/wan_fal_image/node.py",      "wan_fal_image"),
    ("nodes/qwen_layered/node.py",       "qwen_layered"),
    ("nodes/seedvr_runpod/node.py",      "seedvr_runpod"),
    ("nodes/image_compare_rgba/node.py", "image_compare_rgba"),
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

try:
    _load("nodes/ops/server.py")
    print("[Ranomany-ComfyNodes] ops routes registered")
except Exception:
    print(f"[Ranomany-ComfyNodes] ops routes failed:\n{traceback.format_exc()}")

try:
    _load("nodes/load_latest_output/server.py")
    print("[Ranomany-ComfyNodes] latest-output route registered")
except Exception:
    print(f"[Ranomany-ComfyNodes] latest-output route failed:\n{traceback.format_exc()}")

try:
    _load("nodes/video_info/server.py")
    print("[Ranomany-ComfyNodes] video-info route registered")
except Exception:
    print(f"[Ranomany-ComfyNodes] video-info route failed:\n{traceback.format_exc()}")

try:
    _load("nodes/cf_identity/server.py")
    print("[Ranomany-ComfyNodes] cf-identity route registered")
except Exception:
    print(f"[Ranomany-ComfyNodes] cf-identity route failed:\n{traceback.format_exc()}")

try:
    _load("nodes/quota/server.py")
    print("[Ranomany-ComfyNodes] usage/quota routes registered")
except Exception:
    print(f"[Ranomany-ComfyNodes] usage/quota routes failed:\n{traceback.format_exc()}")

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]

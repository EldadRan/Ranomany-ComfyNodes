"""
APIKey — generic environment / .env key resolver for ComfyUI.

Place one node per API service in your workflow, set the key_name to the
environment variable you want (e.g. GEMINI_API_KEY, OPENAI_API_KEY), and
wire the STRING output to any node that needs it.

Resolution order:
  1. Value typed into the api_key input
  2. Environment variable matching key_name
  3. .env file — searched in:
       a. This node's install directory
       b. The custom_nodes directory
       c. The ComfyUI root directory

The node always re-evaluates so the status badge stays current.
"""

import os

_ENV_RELATIVE_PATHS = [".", "..", "../..", "../../..", "../../../.."]


def _read_env_file(directory: str, key_name: str) -> str:
    env_path = os.path.join(directory, ".env")
    if not os.path.isfile(env_path):
        return ""
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == key_name:
                    return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def resolve_key(key_name: str, direct_value: str = "") -> tuple[str, str]:
    """
    Return (key, source) where source is one of:
      'input' | 'env' | 'file' | 'none'
    """
    key = (direct_value or "").strip()
    if key:
        return key, "input"

    key = os.environ.get(key_name, "").strip()
    if key:
        return key, "env"

    node_dir = os.path.dirname(os.path.abspath(__file__))
    for rel in _ENV_RELATIVE_PATHS:
        key = _read_env_file(os.path.normpath(os.path.join(node_dir, rel)), key_name)
        if key:
            return key, "file"

    return "", "none"


_SOURCE_LABELS = {
    "input": "✅ Found in node input",
    "env":   "✅ Found in environment variable",
    "file":  "✅ Found in .env file",
}


class APIKey:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "key_name": ("STRING", {
                    "default": "GEMINI_API_KEY",
                    "tooltip": "Name of the environment variable to look up (e.g. GEMINI_API_KEY, OPENAI_API_KEY).",
                }),
            },
            "optional": {
                "api_key": ("STRING", {
                    "default": "",
                    "password": True,
                    "tooltip": "Paste the key directly here as a fallback. Leave blank to load from env var or .env file.",
                }),
            },
        }

    RETURN_TYPES  = ("STRING", "STRING")
    RETURN_NAMES  = ("api_key", "status")
    FUNCTION      = "resolve"
    CATEGORY      = "Ranomany"
    OUTPUT_NODE   = False

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")  # always re-run so status stays current

    def resolve(self, key_name: str, api_key: str = "") -> dict:
        key_name = key_name.strip()
        if not key_name:
            raise ValueError("APIKey: key_name cannot be empty.")

        key, source = resolve_key(key_name, api_key)

        if not key:
            raise ValueError(
                f"APIKey: no value found for '{key_name}'. "
                f"Set it as an environment variable, add it to a .env file "
                f"(in the ComfyUI root or custom_nodes/), or paste it into the api_key field."
            )

        status = _SOURCE_LABELS.get(source, "✅ Found")
        print(f"[APIKey] {key_name}: {status}")
        return {"ui": {"text": [status]}, "result": (key, status)}


NODE_CLASS_MAPPINGS = {
    "RanomanyAPIKey": APIKey,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RanomanyAPIKey": "API Key",
}

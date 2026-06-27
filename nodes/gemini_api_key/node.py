"""
GeminiAPIKey — ComfyUI API key node for Gemini services.

Place one of these in your workflow and wire its output to any Gemini node.
The key is resolved once and passed as a STRING — never stored in the workflow
in a readable form (the input field is password-masked).

Resolution order:
  1. Value typed into the `api_key` input
  2. GEMINI_API_KEY environment variable
  3. .env file — searched in:
       a. This node's install directory   (custom_nodes/gemini_api_key/.env)
       b. The custom_nodes directory      (custom_nodes/.env)
       c. The ComfyUI root directory      (ComfyUI/.env)
"""

import os

# Locations to search for a .env file, relative to this file's directory.
# __file__ lives at:  <comfyui>/custom_nodes/gemini_api_key/node.py
# so ..  = custom_nodes/
#    ../.. = ComfyUI root
_ENV_RELATIVE_PATHS = [".", "..", "../.."]


def _read_env_file(path: str) -> str:
    """Return the value of GEMINI_API_KEY from a .env file, or ''."""
    env_path = os.path.join(path, ".env")
    if not os.path.isfile(env_path):
        return ""
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == "GEMINI_API_KEY":
                    return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def resolve_gemini_key(api_key_input: str) -> str:
    """Resolve the Gemini API key using the priority chain."""
    key = (api_key_input or "").strip()
    if key:
        return key

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key

    node_dir = os.path.dirname(os.path.abspath(__file__))
    for rel in _ENV_RELATIVE_PATHS:
        key = _read_env_file(os.path.normpath(os.path.join(node_dir, rel)))
        if key:
            return key

    return ""


class GeminiAPIKey:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api_key": ("STRING", {
                    "default": "",
                    "password": True,
                    "tooltip": (
                        "Your Gemini API key. Leave blank to use the GEMINI_API_KEY "
                        "environment variable or a .env file."
                    ),
                }),
            },
        }

    RETURN_TYPES  = ("STRING",)
    RETURN_NAMES  = ("api_key",)
    FUNCTION      = "resolve"
    CATEGORY      = "Ranomany/Gemini"
    OUTPUT_NODE   = False

    def resolve(self, api_key: str = "") -> tuple:
        key = resolve_gemini_key(api_key)
        if not key:
            raise ValueError(
                "GeminiAPIKey: no API key found. "
                "Type it into the node, set GEMINI_API_KEY in your environment, "
                "or create a .env file with GEMINI_API_KEY=... in your ComfyUI root."
            )
        return (key,)


NODE_CLASS_MAPPINGS = {
    "GeminiAPIKey": GeminiAPIKey,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "GeminiAPIKey": "Gemini API Key",
}

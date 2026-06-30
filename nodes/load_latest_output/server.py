"""
Server route for "Load Image (from Outputs)".

  GET /ranomany/latest-output
    -> { "filename": "...", "subfolder": "...", "type": "output" }   (newest by mtime)
    -> { "filename": null } when the output folder has no images.

The JS extension (web/load_image_from_output.js) calls this to set the node's
image widget to the newest output file (by true modification time, which the
browser cannot read on its own).

Self-contained on purpose: the repo loads each node file as a standalone module
(no package context), so it cannot relative-import node.py.
"""

import os

from aiohttp import web
from server import PromptServer

import folder_paths

_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _find_latest(folder: str) -> str | None:
    best_path = None
    best_mtime = -1.0
    for root, _, files in os.walk(folder):
        for fname in files:
            if os.path.splitext(fname)[1].lower() not in _EXTS:
                continue
            full = os.path.join(root, fname)
            try:
                mt = os.path.getmtime(full)
            except OSError:
                continue
            if mt > best_mtime:
                best_mtime = mt
                best_path = full
    return best_path


async def handle_latest_output(request):
    output_dir = folder_paths.get_output_directory()
    latest = _find_latest(output_dir)
    if latest is None:
        return web.json_response({"filename": None})

    rel = os.path.relpath(latest, output_dir)
    subfolder, filename = os.path.split(rel)
    return web.json_response({
        "filename": filename,
        "subfolder": subfolder,
        "type": "output",
    })


r = PromptServer.instance.routes
r.get("/ranomany/latest-output")(handle_latest_output)

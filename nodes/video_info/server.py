"""
Server route for "Load Video (Info)" — probe a picked video without running the graph.

  GET /ranomany/video-info?file=<picker value, e.g. "clip.mp4" or "sub/clip.mp4 [input]">
    -> { "width", "height", "fps", "frame_count", "duration_seconds", "filename" }
    -> { "error": "..." } (HTTP 400/404) when the file is missing or unreadable.

The JS extension calls this the moment the user picks/uploads a clip so the app-mode
info panel fills in immediately — fps and exact frame count aren't available to the
browser's HTML5 video API, only to PyAV on the backend.

Self-contained on purpose: the repo loads each node file as a standalone module (no
package context), so it cannot relative-import node.py. The probe logic mirrors
nodes/video_info/node.py:_probe — keep the two in sync.
"""

import os
import logging

from aiohttp import web
from server import PromptServer

import folder_paths

log = logging.getLogger("VideoInfo")


def _probe(path: str) -> tuple[float, int, float, int, int]:
    """Return (fps, frame_count, duration_seconds, width, height) via PyAV."""
    import av

    with av.open(path) as container:
        stream = container.streams.video[0]

        rate = stream.average_rate or stream.guessed_rate
        fps = float(rate) if rate else 0.0

        width = int(stream.codec_context.width or 0)
        height = int(stream.codec_context.height or 0)

        duration = 0.0
        if container.duration:
            duration = float(container.duration) / float(av.time_base)
        elif stream.duration and stream.time_base:
            duration = float(stream.duration * stream.time_base)

        frame_count = int(stream.frames or 0)
        if frame_count <= 0 and fps > 0 and duration > 0:
            frame_count = round(duration * fps)

    return fps, int(frame_count), duration, width, height


async def handle_video_info(request):
    value = request.query.get("file", "").strip()
    if not value:
        return web.json_response({"error": "missing 'file'"}, status=400)
    if not folder_paths.exists_annotated_filepath(value):
        return web.json_response({"error": f"not found: {value}"}, status=404)

    path = folder_paths.get_annotated_filepath(value)
    try:
        fps, frame_count, duration_seconds, width, height = _probe(path)
    except Exception as exc:
        log.warning(f"[VideoInfo] probe failed for {path!r}: {exc}")
        return web.json_response({"error": str(exc)}, status=400)

    return web.json_response({
        "filename": os.path.basename(path),
        "fps": round(fps, 3),
        "frame_count": frame_count,
        "duration_seconds": round(duration_seconds, 3),
        "width": width,
        "height": height,
    })


r = PromptServer.instance.routes
r.get("/ranomany/video-info")(handle_video_info)

"""
LoadVideoInfo ("Load Video (Info)") — Phase 1 of a video toolset.

Loads a video from the input folder (native video picker + upload button), reads its
metadata (fps, frame count, duration, dimensions) with PyAV, and plays it inline in the
node via a companion JS extension (web/video_info.js), the same way our Save Video node
previews its output.

Outputs a VIDEO handle ({"filepath", "mime_type"}) compatible with our SaveVideo node, plus
the metadata as FLOAT/INT outputs for wiring downstream.

PyAV (`av`) is ffmpeg's libav* exposed to Python — the single library this whole video
toolset is built on (metadata now; frame extraction and trimming in later phases).
"""

import os
import logging

import folder_paths

log = logging.getLogger("VideoInfo")

VIDEO = "VIDEO"


def _list_input_videos() -> list[str]:
    input_dir = folder_paths.get_input_directory()
    if not os.path.isdir(input_dir):
        return []
    files = [
        f for f in os.listdir(input_dir)
        if os.path.isfile(os.path.join(input_dir, f))
    ]
    return sorted(folder_paths.filter_files_content_types(files, ["video"]))


def _split_annotated(value: str) -> tuple[str, str, str]:
    """Split a picker value like "sub/dir/clip.mp4 [input]" into (filename, subfolder, type)."""
    v = (value or "").strip()
    ftype = "input"
    if v.endswith("]") and " [" in v:
        head, _, tail = v.rpartition(" [")
        v, ftype = head, tail[:-1]
    subfolder, _, filename = v.rpartition("/")
    return filename, subfolder, ftype


def _probe(path: str) -> tuple[float, int, float, int, int]:
    """Return (fps, frame_count, duration_seconds, width, height) via PyAV."""
    try:
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
    except Exception as exc:
        log.warning(f"[VideoInfo] failed to probe {path!r}: {exc}")
        return 0.0, 0, 0.0, 0, 0


class LoadVideoInfo:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # Native video picker: input-folder browser + upload button.
                "video": (_list_input_videos(), {"video_upload": True}),
            }
        }

    RETURN_TYPES = (VIDEO, "FLOAT", "INT", "FLOAT", "INT", "INT")
    RETURN_NAMES = ("video", "fps", "frame_count", "duration_seconds", "width", "height")
    FUNCTION     = "load"
    CATEGORY     = "Ranomany/Utils"

    @classmethod
    def IS_CHANGED(cls, video):
        try:
            path = folder_paths.get_annotated_filepath(video)
            return f"{path}:{os.path.getmtime(path)}"
        except Exception:
            return float("nan")

    @classmethod
    def VALIDATE_INPUTS(cls, video):
        if not folder_paths.exists_annotated_filepath(video):
            return f"Invalid video file: {video}"
        return True

    def load(self, video: str):
        path = folder_paths.get_annotated_filepath(video)
        fps, frame_count, duration_seconds, width, height = _probe(path)

        ext = os.path.splitext(path)[1].lstrip(".").lower()
        mime = f"video/{ext}" if ext else "video/mp4"

        filename, subfolder, ftype = _split_annotated(video)
        summary = (
            f"{width}x{height} · {fps:.3f} fps · "
            f"{frame_count} frames · {duration_seconds:.2f}s"
        )

        return {
            "ui": {
                "gifs": [{"filename": filename, "subfolder": subfolder,
                          "type": ftype, "format": mime}],
                "text": [summary],
            },
            "result": ({"filepath": path, "mime_type": mime}, fps, frame_count,
                       duration_seconds, width, height),
        }


NODE_CLASS_MAPPINGS = {
    "RanomanyLoadVideoInfo": LoadVideoInfo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RanomanyLoadVideoInfo": "Load Video (Info)",
}

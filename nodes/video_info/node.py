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
from collections import deque

import folder_paths

log = logging.getLogger("VideoInfo")

VIDEO = "VIDEO"

# Frame-extraction modes (shared with web/video_info.js for the amount relabel).
MODE_FROM_START     = "From start"
MODE_FROM_LAST      = "From last"
MODE_FIRST_EACH_S   = "First frame of each second"
MODE_ALL_OF_S       = "All frames of specific second"
MODE_SPECIFIC_FRAME = "Specific frame"
FRAME_MODES = [MODE_FROM_START, MODE_FROM_LAST, MODE_FIRST_EACH_S, MODE_ALL_OF_S,
               MODE_SPECIFIC_FRAME]

# Short action codes emitted as a text output (FS / FL / ES / SS / SF).
MODE_ABBR = {
    MODE_FROM_START:     "FS",
    MODE_FROM_LAST:      "FL",
    MODE_FIRST_EACH_S:   "ES",
    MODE_ALL_OF_S:       "SS",
    MODE_SPECIFIC_FRAME: "SF",
}

# Frame-trim modes (shared with web/video_info.js for the amount relabel). Trim is the
# inverse of extract: it drops N frames and keeps the rest.
TRIM_FROM_START = "Trim from start"
TRIM_FROM_END   = "Trim from end"
TRIM_MODES      = [TRIM_FROM_START, TRIM_FROM_END]
TRIM_ABBR       = {TRIM_FROM_START: "TS", TRIM_FROM_END: "TE"}

_MAX_FRAMES = 10000  # safety cap: warn + truncate to protect memory


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


def _extract_frames(path: str, mode: str, amount: int):
    """Decode selected frames with PyAV. Returns (ndarray B×H×W×3 uint8, fps)."""
    import numpy as np

    fps, total, duration, width, height = _probe(path)
    frames: list = []

    try:
        import av

        with av.open(path) as container:
            stream = container.streams.video[0]
            stream.thread_type = "AUTO"

            def rgb(frame):
                return frame.to_ndarray(format="rgb24")  # H×W×3 uint8

            if mode == MODE_FROM_START:
                n = amount if amount > 0 else (total or _MAX_FRAMES)
                for frame in container.decode(stream):
                    if len(frames) >= n:
                        break
                    frames.append(rgb(frame))

            elif mode == MODE_FROM_LAST:
                n = amount if amount > 0 else (total or _MAX_FRAMES)
                dq = deque(maxlen=n if n > 0 else None)
                for frame in container.decode(stream):
                    dq.append(rgb(frame))
                frames = list(dq)

            elif mode == MODE_FIRST_EACH_S:
                targets = set()
                s = 0
                limit = total if total > 0 else round((duration or 0) * fps) + 1
                while fps > 0:
                    i = round(s * fps)
                    if i >= limit:
                        break
                    targets.add(i)
                    s += 1
                    if s > _MAX_FRAMES:
                        break
                for idx, frame in enumerate(container.decode(stream)):
                    if idx in targets:
                        frames.append(rgb(frame))

            elif mode == MODE_ALL_OF_S:
                S = max(0, int(amount))
                start_i = round(S * fps)
                end_i = round((S + 1) * fps)
                for idx, frame in enumerate(container.decode(stream)):
                    if idx >= end_i:
                        break
                    if idx >= start_i:
                        frames.append(rgb(frame))

            elif mode == MODE_SPECIFIC_FRAME:
                target = max(0, int(amount))
                for idx, frame in enumerate(container.decode(stream)):
                    if idx == target:
                        frames.append(rgb(frame))
                        break

            else:
                log.warning(f"[VideoInfo] unknown extract mode {mode!r}")

        if len(frames) > _MAX_FRAMES:
            log.warning(
                f"[VideoInfo] extracted {len(frames)} frames, truncating to {_MAX_FRAMES}."
            )
            frames = frames[:_MAX_FRAMES]
    except Exception as exc:
        log.warning(f"[VideoInfo] failed to extract frames from {path!r}: {exc}")
        frames = []

    if not frames:
        log.warning(f"[VideoInfo] no frames extracted (mode={mode!r}, amount={amount}).")
        black = np.zeros((height or 64, width or 64, 3), dtype=np.uint8)
        frames = [black]

    return np.stack(frames), fps


def _trim_frames(path: str, mode: str, amount: int):
    """Decode a clip and drop N frames from the start or end. Returns (ndarray B×H×W×3, fps)."""
    import numpy as np

    fps, total, duration, width, height = _probe(path)
    n = max(0, int(amount))
    frames: list = []

    try:
        import av

        with av.open(path) as container:
            stream = container.streams.video[0]
            stream.thread_type = "AUTO"

            def rgb(frame):
                return frame.to_ndarray(format="rgb24")  # H×W×3 uint8

            if mode == TRIM_FROM_START:
                # Skip the first n frames as we decode — never materialise the dropped ones.
                for idx, frame in enumerate(container.decode(stream)):
                    if idx < n:
                        continue
                    frames.append(rgb(frame))

            elif mode == TRIM_FROM_END:
                # Need the total to know where the tail begins, so decode all then slice.
                for frame in container.decode(stream):
                    frames.append(rgb(frame))
                # max(0, …) so trimming >= total yields empty (a bare negative slice
                # index would wrongly keep frames from the front).
                frames = frames[:max(0, len(frames) - n)] if n > 0 else frames

            else:
                log.warning(f"[VideoInfo] unknown trim mode {mode!r}")

        if len(frames) > _MAX_FRAMES:
            log.warning(
                f"[VideoInfo] trimmed to {len(frames)} frames, truncating to {_MAX_FRAMES}."
            )
            frames = frames[:_MAX_FRAMES]
    except Exception as exc:
        log.warning(f"[VideoInfo] failed to trim frames from {path!r}: {exc}")
        frames = []

    if not frames:
        log.warning(f"[VideoInfo] no frames left after trim (mode={mode!r}, amount={amount}).")
        black = np.zeros((height or 64, width or 64, 3), dtype=np.uint8)
        frames = [black]

    return np.stack(frames), fps


class LoadVideoInfo:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # Native video picker: input-folder browser + upload button.
                "video": (_list_input_videos(), {"video_upload": True}),
            }
        }

    RETURN_TYPES = (VIDEO, "FLOAT", "INT", "FLOAT", "INT", "INT", "STRING", "STRING")
    RETURN_NAMES = ("video", "fps", "frame_count", "duration_seconds", "width", "height",
                    "filename", "file_extension")
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
        name_no_ext, dot_ext = os.path.splitext(filename)
        file_extension = dot_ext.lstrip(".")

        return {
            "ui": {
                "gifs": [{"filename": filename, "subfolder": subfolder,
                          "type": ftype, "format": mime}],
                # Structured metadata for the app-mode info widget (web/video_info.js).
                "video_info": [{
                    "filename": filename,
                    "fps": round(fps, 3),
                    "frame_count": frame_count,
                    "duration_seconds": round(duration_seconds, 3),
                    "width": width,
                    "height": height,
                }],
            },
            "result": ({"filepath": path, "mime_type": mime}, fps, frame_count,
                       duration_seconds, width, height, name_no_ext, file_extension),
        }


class ExtractVideoFrames:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video":  (VIDEO,),
                "mode":   (FRAME_MODES, {"default": MODE_FROM_START}),
                "amount": ("INT", {"default": 1, "min": 0, "max": 1_000_000,
                                   "tooltip": "From start/last: how many frames. "
                                              "Specific second: which second (0-based). "
                                              "Specific frame: which frame index (0-based). "
                                              "First frame of each second: ignored."}),
            }
        }

    RETURN_TYPES = ("IMAGE", "INT", "FLOAT", "STRING")
    RETURN_NAMES = ("images", "frame_count", "fps", "action")
    FUNCTION     = "extract"
    CATEGORY     = "Ranomany/Utils"

    def extract(self, video: dict, mode: str, amount: int):
        import numpy as np
        import torch

        path = video["filepath"]
        arr, fps = _extract_frames(path, mode, amount)
        images = torch.from_numpy(arr.astype(np.float32) / 255.0)  # B×H×W×3
        return (images, int(arr.shape[0]), float(fps), MODE_ABBR.get(mode, ""))


class TrimVideoFrames:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video":  (VIDEO,),
                "mode":   (TRIM_MODES, {"default": TRIM_FROM_START}),
                "amount": ("INT", {"default": 1, "min": 0, "max": 12,
                                   "tooltip": "How many frames to remove from the start / end "
                                              "(0-12). 0 keeps all frames."}),
            }
        }

    RETURN_TYPES = ("IMAGE", "INT", "FLOAT", "STRING")
    RETURN_NAMES = ("images", "frame_count", "fps", "action")
    FUNCTION     = "trim"
    CATEGORY     = "Ranomany/Utils"

    def trim(self, video: dict, mode: str, amount: int):
        import numpy as np
        import torch

        path = video["filepath"]
        arr, fps = _trim_frames(path, mode, amount)
        images = torch.from_numpy(arr.astype(np.float32) / 255.0)  # B×H×W×3
        return (images, int(arr.shape[0]), float(fps), TRIM_ABBR.get(mode, ""))


NODE_CLASS_MAPPINGS = {
    "RanomanyLoadVideoInfo":      LoadVideoInfo,
    "RanomanyExtractVideoFrames": ExtractVideoFrames,
    "RanomanyTrimVideoFrames":    TrimVideoFrames,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RanomanyLoadVideoInfo":      "Load Video (Info)",
    "RanomanyExtractVideoFrames": "Extract Video Frames",
    "RanomanyTrimVideoFrames":    "Trim Video Frames",
}

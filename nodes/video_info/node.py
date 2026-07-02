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

# FPS-conversion methods. Each maps to a libavfilter chain applied via av.filter.Graph —
# the same recipes you'd write on the ffmpeg CLI, but run through PyAV (no ffmpeg binary).
FPS_RETIME       = "Re-time (change speed)"
FPS_DUPLICATE    = "Duplicate frames"
FPS_BLEND        = "Blend (framerate)"
FPS_MINTERP      = "Motion interpolation"
FPS_MINTERP_BEST = "Motion interpolation (best)"
FPS_DEDUP        = "Dedup + resample"
FPS_METHODS = [FPS_DUPLICATE, FPS_BLEND, FPS_MINTERP, FPS_MINTERP_BEST, FPS_DEDUP, FPS_RETIME]

# method -> list of (filter_name, args_template). [] = identity (re-time: keep the same frames,
# just re-timestamp at the new rate → changes speed). "{dst}" is the target fps.
_FPS_CHAINS = {
    FPS_RETIME:       [],
    FPS_DUPLICATE:    [("fps", "{dst}")],
    FPS_BLEND:        [("framerate", "fps={dst}")],
    FPS_MINTERP:      [("minterpolate", "fps={dst}")],
    FPS_MINTERP_BEST: [("minterpolate", "fps={dst}:mi_mode=mci:mc_mode=aobmc:vsbmc=1")],
    FPS_DEDUP:        [("mpdecimate", ""), ("fps", "{dst}")],
}

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


def _trim_video(path: str, mode: str, amount: int) -> tuple[str, int]:
    """Trim a clip and re-encode the kept frames to a temp mp4 (H.264).

    Returns (output_filepath, frame_count). The file is written like our other VIDEO
    producers (a NamedTemporaryFile) so SaveVideo can move it to the output directory.
    """
    import tempfile
    from fractions import Fraction

    import av

    arr, fps = _trim_frames(path, mode, amount)  # B×H×W×3 uint8
    height, width = int(arr.shape[1]), int(arr.shape[2])
    rate = Fraction(fps).limit_denominator(1000) if fps and fps > 0 else Fraction(24, 1)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    tmp.close()

    with av.open(tmp.name, mode="w") as out:
        ostream = out.add_stream("libx264", rate=rate)
        ostream.width = width
        ostream.height = height
        ostream.pix_fmt = "yuv420p"
        for i in range(arr.shape[0]):
            frame = av.VideoFrame.from_ndarray(arr[i], format="rgb24")
            for packet in ostream.encode(frame):
                out.mux(packet)
        for packet in ostream.encode():  # flush the encoder
            out.mux(packet)

    log.info(f"[VideoInfo] trimmed video ({arr.shape[0]} frames) → {tmp.name}")
    return tmp.name, int(arr.shape[0])


def _convert_fps(path: str, method: str, target_fps: int) -> tuple[str, int]:
    """Convert a clip's frame rate to target_fps and re-encode to a temp mp4 (H.264).

    Decodes with PyAV, pushes frames through a libavfilter graph (the chain for `method`),
    then re-encodes the filtered frames at `target_fps`. Re-time uses an empty chain: the
    same frames are muxed at the new rate, changing playback speed. Returns (path, fps).
    """
    import tempfile
    from fractions import Fraction

    import av

    dst = max(1, int(target_fps))
    chain = _FPS_CHAINS.get(method)
    if chain is None:
        raise ValueError(f"unknown fps method {method!r}")
    rate = Fraction(dst, 1)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    tmp.close()

    written = 0
    with av.open(path) as container, av.open(tmp.name, mode="w") as out:
        istream = container.streams.video[0]
        istream.thread_type = "AUTO"

        ostream = out.add_stream("libx264", rate=rate)
        ostream.pix_fmt = "yuv420p"

        # Build the filter graph only when the method actually filters (re-time is identity).
        graph = None
        sink = None
        if chain:
            graph = av.filter.Graph()
            prev = graph.add_buffer(template=istream)
            for name, args_tpl in chain:
                args = args_tpl.format(dst=dst)
                try:
                    node = graph.add(name, args) if args else graph.add(name)
                except Exception as exc:
                    raise RuntimeError(
                        f"filter {name!r} unavailable in this PyAV/libav build ({exc})"
                    ) from exc
                prev.link_to(node)
                prev = node
            sink = graph.add("buffersink")
            prev.link_to(sink)
            graph.configure()

        def emit(frame):
            nonlocal written
            if ostream.width == 0:
                ostream.width = frame.width
                ostream.height = frame.height
            # Clear pts so the encoder assigns sequential timestamps at the output rate
            # (CFR). time_base must stay a real rational — PyAV rejects None there.
            frame.pts = None
            for packet in ostream.encode(frame):
                out.mux(packet)
            written += 1

        def drain():
            while True:
                try:
                    emit(graph.pull())
                except (av.error.BlockingIOError, av.error.EOFError):
                    break

        for frame in container.decode(istream):
            if graph is not None:
                graph.push(frame)
                drain()
            else:
                emit(frame)

        if graph is not None:
            graph.push(None)  # signal end-of-stream so filters (e.g. minterpolate) flush
            drain()

        for packet in ostream.encode():  # flush the encoder
            out.mux(packet)

    log.info(f"[VideoInfo] converted fps ({method}, → {dst} fps, {written} frames) → {tmp.name}")
    return tmp.name, dst


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
    CATEGORY     = "Ranomany/Media Tools"

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

    RETURN_TYPES = (VIDEO, "INT", "STRING")
    RETURN_NAMES = ("video", "frame_count", "action")
    FUNCTION     = "trim"
    CATEGORY     = "Ranomany/Media Tools"

    def trim(self, video: dict, mode: str, amount: int):
        path = video["filepath"]
        out_path, frame_count = _trim_video(path, mode, amount)
        return ({"filepath": out_path, "mime_type": "video/mp4"}, frame_count,
                TRIM_ABBR.get(mode, ""))


class ConvertVideoFPS:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video":      (VIDEO,),
                "method":     (FPS_METHODS, {"default": FPS_DUPLICATE}),
                "target_fps": ("INT", {"default": 30, "min": 1, "max": 240,
                                       "tooltip": "Output frames per second. Duration-preserving "
                                                  "methods add/drop frames to hit this; "
                                                  "Re-time changes playback speed instead."}),
            }
        }

    RETURN_TYPES = (VIDEO, "INT")
    RETURN_NAMES = ("video", "fps")
    FUNCTION     = "convert"
    CATEGORY     = "Ranomany/Media Tools"

    def convert(self, video: dict, method: str, target_fps: int):
        out_path, fps = _convert_fps(video["filepath"], method, target_fps)
        return ({"filepath": out_path, "mime_type": "video/mp4"}, fps)


NODE_CLASS_MAPPINGS = {
    "RanomanyLoadVideoInfo":      LoadVideoInfo,
    "RanomanyExtractVideoFrames": ExtractVideoFrames,
    "RanomanyTrimVideoFrames":    TrimVideoFrames,
    "RanomanyConvertVideoFPS":    ConvertVideoFPS,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "RanomanyLoadVideoInfo":      "Load Video (Info)",
    "RanomanyExtractVideoFrames": "Extract Video Frames",
    "RanomanyTrimVideoFrames":    "Trim Video Frames",
    "RanomanyConvertVideoFPS":    "Convert Video FPS",
}

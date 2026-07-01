# Ranomany-ComfyNodes

Shared ComfyUI custom-node pack used across Ranomany projects.

**Layout** — one node per subdirectory under `nodes/`. Each subdir is a self-contained ComfyUI custom node that can be installed on its own by copying the directory into `custom_nodes/`. This lets each endpoint pick the subset it actually needs.

```
Ranomany-ComfyNodes/
├── README.md
├── manifest.yaml                # node_name -> {description, deps, version}
├── web/                         # JS extensions auto-loaded by ComfyUI frontend
│   ├── save_video.js            # Inline video preview for Save Video node
│   ├── camera_angle.bundle.js   # 3D camera-angle GUI (Vue + Three.js, built)
│   ├── load_image_from_output.js# App-mode <img> preview + refresh for Load Image (Edit Mode)
│   ├── video_info.js            # Inline video player for Load Video (Info)
│   └── assets/main.css          # Styles for the camera-angle GUI
└── nodes/
    ├── api_key/                 # Generic API key resolver (any provider)
    ├── gemini_image/            # Image generation / editing via Gemini
    ├── gemini_veo/              # Video generation via Veo + Save Video node
    ├── openai_image/            # Image generation / editing via OpenAI gpt-image-2
    ├── save_image_no_meta/      # Save PNG without workflow metadata
    ├── wan_image/               # Image generation / editing via Alibaba Wan 2.7
    ├── wan_video/               # Video generation / editing via Alibaba Wan 2.7
    ├── camera_angle/            # 3D Camera Angle control + Camera Angle (Load Image)
    │   └── gui/                 # Vue + Three.js source for the GUI bundle (rebuildable)
    ├── load_latest_output/      # Load Image (Edit Mode) — native picker + newest-output
    └── video_info/              # Load Video (Info) — metadata + inline playback (PyAV)
```

---

## Installing into ComfyUI

Copy the subdirectory (or directories) you need into your ComfyUI `custom_nodes/` folder:

```bash
cp -r nodes/api_key            /path/to/ComfyUI/custom_nodes/
cp -r nodes/gemini_image       /path/to/ComfyUI/custom_nodes/
cp -r nodes/gemini_veo         /path/to/ComfyUI/custom_nodes/
cp -r nodes/openai_image       /path/to/ComfyUI/custom_nodes/
cp -r nodes/save_image_no_meta /path/to/ComfyUI/custom_nodes/
cp -r nodes/wan_image          /path/to/ComfyUI/custom_nodes/
cp -r nodes/wan_video          /path/to/ComfyUI/custom_nodes/
```

> **Note — `camera_angle` and `load_latest_output` need the full repo.** Unlike the
> self-contained API nodes above, the **Camera Angle**, **Camera Angle (Load Image)**, and
> **Load Image (Edit Mode)** nodes rely on frontend assets served from the repo-root `web/`
> directory (`camera_angle.bundle.js`, `load_image_from_output.js`, `assets/main.css`) via
> the root `__init__.py`'s `WEB_DIRECTORY`. Copying just their `nodes/<name>/` subdirectory
> will register the Python node but **omit its GUI/preview** (and, for Load Image (Edit Mode),
> the `/ranomany/latest-output` route). To use these nodes, install the whole repo as one
> custom node:
>
> ```bash
> git clone https://github.com/EldadRan/Ranomany-ComfyNodes.git \
>     /path/to/ComfyUI/custom_nodes/Ranomany-ComfyNodes
> ```

Install dependencies:

```bash
pip install google-genai>=1.0.0   # required by gemini_image and gemini_veo
pip install openai>=1.0.0          # required by openai_image
pip install mutagen>=1.47.0        # optional — enables MP4 metadata embedding in Save Video
# wan_image and wan_video use stdlib only — no extra dependencies
```

### Pinning by SHA in a Dockerfile

```dockerfile
ARG RANOMANY_COMFYNODES_SHA=<commit-sha>
RUN git clone https://github.com/EldadRan/Ranomany-ComfyNodes.git /tmp/cn && \
    cd /tmp/cn && git checkout "$RANOMANY_COMFYNODES_SHA" && \
    cp -r /tmp/cn/nodes/api_key            /comfyui/custom_nodes/ && \
    cp -r /tmp/cn/nodes/gemini_image       /comfyui/custom_nodes/ && \
    cp -r /tmp/cn/nodes/gemini_veo         /comfyui/custom_nodes/ && \
    cp -r /tmp/cn/nodes/openai_image       /comfyui/custom_nodes/ && \
    cp -r /tmp/cn/nodes/save_image_no_meta /comfyui/custom_nodes/ && \
    cp -r /tmp/cn/nodes/wan_image          /comfyui/custom_nodes/ && \
    cp -r /tmp/cn/nodes/wan_video          /comfyui/custom_nodes/ && \
    pip install google-genai>=1.0.0 openai>=1.0.0 mutagen>=1.47.0
```

---

## Nodes

### `api_key` — API Key

A generic key resolver that works for **any API provider**. Place one node per service in your workflow, set `key_name` to the environment variable you want, and wire the STRING output to any node that needs it.

After the workflow runs, the node shows a status badge indicating where the key was found.

**Category:** `Ranomany`

| Input | Type | Notes |
|---|---|---|
| `key_name` | STRING | Environment variable name to look up — e.g. `GEMINI_API_KEY`, `OPENAI_API_KEY` |
| `api_key` | STRING (masked) | Direct fallback — paste the key here if env var / `.env` are not set |

| Output | Type | Description |
|---|---|---|
| `api_key` | STRING | Resolved key, ready to wire to any generation node |

**Status badge** (shown on the node after execution):
- `✅ Found in node input`
- `✅ Found in environment variable`
- `✅ Found in .env file`

**Key resolution order:**
1. Value typed into the `api_key` field
2. Environment variable matching `key_name`
3. `.env` file — searched in the node's install dir → `custom_nodes/` → ComfyUI root

**`.env` file** (create once in the ComfyUI root, already in `.gitignore`):
```
GEMINI_API_KEY=AIza...
OPENAI_API_KEY=sk-...
```

**Example — one key node wired to multiple generation nodes:**
```
[API Key]  key_name=GEMINI_API_KEY
    │ api_key
    ├──► [Gemini Image Generate]
    └──► [Gemini Veo Generate]
```

---

### `gemini_image` — Gemini Image Generate

Generate images from text, or edit/compose existing images using the Gemini multimodal API. Outputs a standard ComfyUI `IMAGE` batch tensor — plug it directly into any downstream node (e.g. `Save Image (no workflow metadata)`).

**Category:** `Ranomany/Gemini`
**Dependencies:** `google-genai>=1.0.0`

#### Inputs

| Input | Type | Default | Notes |
|---|---|---|---|
| `prompt` | STRING | — | Describe what you want. Can be blank if you supply an input image. |
| `model` | dropdown | `gemini-3.1-flash-image-preview` | Flash = fast & cheap; Pro = highest quality (enables thinking) |
| `image` | IMAGE | *(optional)* | Input image(s) for editing or composition. Accepts the full batch — refer to images in your prompt as "first image", "second image", etc. Up to 14 images. |
| `api_key` | STRING (masked) | *(optional)* | Wire from `API Key` node, or leave blank to use env var / `.env` file |
| `image_size` | dropdown | `1K` | Output resolution: `1K`, `2K`, or `4K` |
| `aspect_ratio` | dropdown | `none` | `none`, `1:1`, `16:9`, `9:16`, `4:3`, `3:4` |
| `thinking_level` | dropdown | `low` | `low` or `high` — only applies to the Pro model |
| `retries` | INT (0–3) | `0` | Auto-retry on transient errors (429, 500–504) with backoff |

#### Outputs

| Output | Type | Description |
|---|---|---|
| `images` | IMAGE | Batch tensor (B×H×W×3, float32, 0–1). One tensor per image returned by the model. |

#### Example workflows

**Text to image:**
```
[API Key] key_name=GEMINI_API_KEY ──api_key──► [Gemini Image Generate]
                    prompt = "A serene Japanese garden at golden hour, photorealistic"
                    ──images──► [Save Image (no workflow metadata)]
```

**Image editing:**
```
[Load Image] ──image──► [Gemini Image Generate]
                prompt = "Remove the background and replace it with a white studio backdrop"
                ──images──► [Preview Image]
```

---

### `gemini_image` — Gemini Image Edit (Multi-Ref)

Editing / composition variant of the Gemini node with **one mandatory image plus up to three optional reference images**. The primary `image` is always sent to the model first; `image_2`–`image_4` are appended in order as additional references (Gemini processes image parts in order). Same output as the base node.

**Category:** `Ranomany/Gemini`
**Dependencies:** `google-genai>=1.0.0`

#### Inputs

| Input | Type | Default | Notes |
|---|---|---|---|
| `prompt` | STRING | — | Refer to the inputs as "first image", "second image", etc. |
| `model` | dropdown | `gemini-3.1-flash-image-preview` | Flash = fast & cheap; Pro = highest quality (enables thinking) |
| `image` | IMAGE | **required** | Primary image — always sent first. Accepts a batch. |
| `image_2` / `image_3` / `image_4` | IMAGE | *(optional)* | Additional reference images, appended in order. Each accepts a batch. |
| `use_image_2` / `use_image_3` / `use_image_4` | BOOLEAN | `use` | Set to `skip` to ignore that slot at run time even when a loader is wired to it. Useful in app mode, where a loader always emits an image. |
| `api_key` | STRING (masked) | *(optional)* | Wire from `API Key` node, or leave blank to use env var / `.env` file |
| `image_size` | dropdown | `1K` | Output resolution: `1K`, `2K`, or `4K` |
| `aspect_ratio` | dropdown | `none` | `none`, `1:1`, `16:9`, `9:16`, `4:3`, `3:4` |
| `thinking_level` | dropdown | `low` | `low` or `high` — only applies to the Pro model |
| `retries` | INT (0–3) | `0` | Auto-retry on transient errors (429, 500–504) with backoff |

#### Outputs

| Output | Type | Description |
|---|---|---|
| `images` | IMAGE | Batch tensor (B×H×W×3, float32, 0–1). |
| `key_status` | STRING | How the API key was resolved. |

#### Example workflow

```
[Load Image] ─────image───► [Gemini Image Edit (Multi-Ref)]
[Load Image] ─────image_2──►   prompt = "Place the product from the first image
[Load Image] ─────image_3──►            into the scene from the second image"
                               ──images──► [Preview Image]
```

---

### `openai_image` — OpenAI Image Generate

Generate images from text, or edit/inpaint existing images using OpenAI's `gpt-image-2` (ChatGPT Images 2.0). Outputs a standard ComfyUI `IMAGE` batch tensor.

**Category:** `Ranomany/OpenAI`
**Dependencies:** `openai>=1.0.0`

#### Inputs

| Input | Type | Default | Notes |
|---|---|---|---|
| `prompt` | STRING | — | Describe what you want. Required unless `image` is supplied. |
| `model` | dropdown | `gpt-image-2` | Currently only `gpt-image-2` |
| `image` | IMAGE | *(optional)* | Input image for editing. Connecting this switches the node to edit mode. |
| `mask` | MASK | *(optional)* | Inpainting mask — `1` = edit here, `0` = keep. Only used in edit mode. |
| `api_key` | STRING (masked) | *(optional)* | Wire from `API Key` node, or leave blank to use env var / `.env` file |
| `size` | STRING | `1024x1024` | `WxH` or `auto`. Dims must be multiples of 16, max edge 3840px, ratio ≤3:1, pixels 655,360–8,294,400. |
| `quality` | dropdown | `auto` | `auto`, `low`, `medium`, `high` |
| `background` | dropdown | `auto` | `auto`, `opaque` (`transparent` is not supported by gpt-image-2) |
| `output_format` | dropdown | `png` | `png`, `jpeg`, `webp` |
| `output_compression` | INT (0–100) | `85` | Compression for `jpeg`/`webp`. Ignored for `png`. |
| `moderation` | dropdown | `auto` | `auto`, `low` — content filtering strictness |
| `n` | INT (1–10) | `1` | Number of images to generate |
| `retries` | INT (0–3) | `0` | Auto-retry on transient 429/5xx errors |

#### Outputs

| Output | Type | Description |
|---|---|---|
| `images` | IMAGE | Batch tensor (B×H×W×3, float32, 0–1). One tensor per image returned. |

#### Example workflows

**Text to image:**
```
[API Key] key_name=OPENAI_API_KEY ──api_key──► [OpenAI Image Generate]
                    prompt = "A photorealistic golden retriever on a misty mountain"
                    size   = 1024x1024
                    ──images──► [Save Image (no workflow metadata)]
```

**Image editing / inpainting:**
```
[Load Image] ──image──► [OpenAI Image Generate]
[Mask Editor] ──mask──►     prompt = "Replace the sky with a dramatic sunset"
                            ──images──► [Preview Image]
```

**`.env` file** (create once in the ComfyUI root):
```
OPENAI_API_KEY=sk-...
```

---

### `openai_image` — OpenAI Image Edit (Multi-Ref)

Editing / composition variant of the OpenAI node with **one mandatory image plus up to three optional reference images**. Always runs in edit mode (`images.edit`). The primary `image` is sent first — gpt-image preserves it with the highest fidelity — and `image_2`–`image_4` are appended as extra references. The OpenAI edit endpoint accepts up to **16 images** total (batches are flattened; anything beyond 16 is dropped with a warning).

**Category:** `Ranomany/OpenAI`
**Dependencies:** `openai>=1.0.0`

#### Inputs

| Input | Type | Default | Notes |
|---|---|---|---|
| `prompt` | STRING | — | Describe the edit / composition. |
| `model` | dropdown | `gpt-image-2` | Currently only `gpt-image-2` |
| `image` | IMAGE | **required** | Primary image — sent first, preserved with highest fidelity. |
| `image_2` / `image_3` / `image_4` | IMAGE | *(optional)* | Additional reference images, appended in order. |
| `use_image_2` / `use_image_3` / `use_image_4` | BOOLEAN | `use` | Set to `skip` to ignore that slot at run time even when a loader is wired to it. Useful in app mode, where a loader always emits an image. |
| `mask` | MASK | *(optional)* | Inpainting mask for the **primary** image — `1` = edit here, `0` = keep. |
| `api_key` | STRING (masked) | *(optional)* | Wire from `API Key` node, or leave blank to use env var / `.env` file |
| `width` / `height` | INT | `1024` | Snapped to multiples of 16, max edge 3840px, ratio ≤3:1, pixels 655,360–8,294,400 (auto-corrected). |
| `n` | INT (1–10) | `1` | Number of images to generate |
| `retries` | INT (0–3) | `0` | Auto-retry on transient 429/5xx errors |

#### Outputs

| Output | Type | Description |
|---|---|---|
| `images` | IMAGE | Batch tensor (B×H×W×3, float32, 0–1). |
| `key_status` | STRING | How the API key was resolved. |

#### Example workflow

```
[Load Image] ─────image───► [OpenAI Image Edit (Multi-Ref)]
[Load Image] ─────image_2──►   prompt = "Composite the subject from the first image
[Load Image] ─────image_3──►            with the background from the second"
                               ──images──► [Save Image (no workflow metadata)]
```

---

### `gemini_veo` — Gemini Veo Generate

Generate videos using Google's Veo model. The node blocks until generation completes (typically 1–3 minutes), then outputs a `VIDEO` value that you wire to a **Save Video** node.

**Category:** `Ranomany/Gemini`
**Dependencies:** `google-genai>=1.0.0`

#### Inputs

| Input | Type | Default | Notes |
|---|---|---|---|
| `prompt` | STRING | — | Describe the video. Can be blank if you supply a first frame. |
| `model` | dropdown | `veo-3.1-generate-preview` | `veo-3.1-generate-preview`, `veo-3.1-fast-generate-preview`, `veo-3.1-lite-generate-preview` |
| `aspect_ratio` | dropdown | `16:9` | `16:9` or `9:16` |
| `resolution` | dropdown | `1080p` | `720p`, `1080p`, or `4k` (Lite model does not support `4k`) |
| `duration_seconds` | INT | `8` | `4` or `8` |
| `first_frame` | IMAGE | *(optional)* | Anchor the first frame of the video to this image |
| `last_frame` | IMAGE | *(optional)* | Anchor the last frame of the video to this image. **Only supported by `veo-3.1-generate-preview`** — raises an error on fast/lite models. |
| `negative_prompt` | STRING | *(optional)* | Things to avoid in the output (e.g. `blur, low quality, distorted faces`) |
| `api_key` | STRING (masked) | *(optional)* | Wire from `API Key` node, or leave blank to use env var / `.env` file |
| `max_wait` | INT | `600` | Seconds before the node gives up (60–1800) |
| `poll_interval` | INT | `10` | Seconds between status polls (5–60) |

#### Outputs

| Output | Type | Description |
|---|---|---|
| `video` | VIDEO | Video data (filepath dict). Wire to **Save Video** to write the MP4 to disk. |

#### Example workflow

```
[API Key] key_name=GEMINI_API_KEY ──api_key──► [Gemini Veo Generate] ──video──► [Save Video]
                    prompt           = "A drone slowly flies over a misty mountain forest at dawn, cinematic"
                    model            = veo-3.1-generate-preview
                    aspect_ratio     = 16:9
                    resolution       = 1080p
                    duration_seconds = 8
```

**Image-to-video:**
```
[Load Image] ──first_frame──► [Gemini Veo Generate] ──video──► [Save Video]
                prompt = "The camera slowly pulls back to reveal the full landscape"
```

---

### `save_video` — Save Video

Writes a VIDEO output from **Gemini Veo Generate** (or any node that produces a VIDEO) to ComfyUI's output directory as an MP4 file. Displays the video in the ComfyUI UI after saving.

**Category:** `Ranomany`
**Dependencies:** none

| Input | Type | Notes |
|---|---|---|
| `video` | VIDEO | Wire from `Gemini Veo Generate` |
| `filename_prefix` | STRING | Prefix for the saved MP4 filename (default: `video`) |
| `extra_metadata` | STRING | Optional JSON object — each key/value is written as a custom MP4 metadata atom. Example: `{"prompt": "misty forest", "model": "veo-3.1-generate-preview"}` |

| Output | Type | Description |
|---|---|---|
| `filepath` | STRING | Full path to the saved MP4 file |

Metadata is stored as custom QuickTime atoms (`----:com.ranomany.comfynodes:KEY`). To read them on your Mac:

```bash
exiftool video_00001_.mp4
```

**Note:** MP4 does not use EXIF. The `extra_metadata` JSON format is the same as `SaveImageNoMeta`, but the storage mechanism is QuickTime atoms (MP4's native metadata system). Requires `mutagen>=1.47.0` (`pip install mutagen`).

---

### `video_info` — Load Video (Info)

Loads a video from the ComfyUI input folder (native picker with an **upload** button), reads its metadata, and **plays it inline** in the node — the same in-node playback as **Save Video**. It also passes the video through as a `VIDEO` handle, so you can wire it straight into **Save Video** or other video nodes.

This is Phase 1 of a PyAV-backed video toolset; later phases (frame extraction to `IMAGE`, trimming from frame N) build on the same `av` dependency.

**Category:** `Ranomany/Utils`
**Dependencies:** `av>=11.0` (PyAV — ffmpeg's libraries in-process; no ffmpeg binary needed)

| Input | Type | Notes |
|---|---|---|
| `video` | picker + upload | Choose a video from the input folder or upload one |

| Output | Type | Description |
|---|---|---|
| `video` | VIDEO | Filepath dict (`{"filepath", "mime_type"}`). Wire to **Save Video** or another video node. |
| `fps` | FLOAT | Frames per second (from `avg_frame_rate`) |
| `frame_count` | INT | Total frames. Falls back to `round(duration × fps)` when the container doesn't report a frame count. |
| `duration_seconds` | FLOAT | Duration in seconds |
| `width` | INT | Frame width in pixels |
| `height` | INT | Frame height in pixels |

In **app mode** the node shows an info panel (resolution / fps / frames / duration) that fills in **as soon as you pick or upload a clip** — no graph run needed. It's backed by a small `GET /ranomany/video-info` route that runs the same PyAV probe (fps and exact frame count aren't available to the browser's HTML5 video API).

An unreadable/corrupt file logs a warning and returns zeros rather than failing the run.

```
[Load Video (Info)] ──video──► [Save Video]
                    ──fps───► ...
                    ──frame_count──► ...
```

---

### `save_image_no_meta` — Save Image (no workflow metadata)

ComfyUI's stock `SaveImage` embeds the entire workflow JSON in PNG `tEXt` chunks. This leaks your workflow to anyone who downloads the image and bloats file size. `SaveImageNoMeta` saves clean PNGs and embeds **only** the keys you explicitly pass via `extra_metadata`.

**Category:** `image/save`
**Dependencies:** none

| Input | Type | Notes |
|---|---|---|
| `images` | IMAGE | Same as core `SaveImage` |
| `filename_prefix` | STRING | Same as core `SaveImage` |
| `extra_metadata` | STRING | Optional JSON object — each key/value is written as a PNG `tEXt` chunk. Pass `""` or `"{}"` for fully clean output. Example: `{"seed": "12345", "model": "flux2"}` |

---

### `wan_image` — Wan Image Generate

Generate images from text, or edit/compose existing images via Alibaba Cloud Wan 2.7. Outputs a standard ComfyUI `IMAGE` batch tensor.

**Category:** `Ranomany/Alibaba`
**Dependencies:** none (Python stdlib only)
**API key env var:** `DASHSCOPE_API_KEY`

#### Inputs

| Input | Type | Default | Notes |
|---|---|---|---|
| `prompt` | STRING | — | Text description (up to 5000 chars). Required unless `image` is supplied. |
| `model` | dropdown | `wan2.7-image-pro` | `wan2.7-image-pro` (higher quality, supports thinking & 4K) or `wan2.7-image` |
| `image` | IMAGE | *(optional)* | Input image(s) for editing/composition. Each frame in a batch becomes a separate image in the request (max 9). |
| `api_key` | STRING (masked) | *(optional)* | Wire from `API Key` node, or leave blank to use `DASHSCOPE_API_KEY` env var / `.env` |
| `workspace_id` | STRING | *(optional)* | Singapore workspace ID (e.g. `ws-xxxxxxxx`). Leave blank to use the Beijing endpoint. |
| `size` | dropdown | `2K` | `1K`, `2K`, `4K` (4K: pro model + text-to-image only) |
| `n` | INT (1–4) | `1` | Number of images to generate per call |
| `thinking_mode` | dropdown | `true` | Enhanced quality pass. Pro model + text-to-image only. Increases latency. |
| `enable_sequential` | dropdown | `false` | Image set mode — generates a coherent sequence from one prompt |
| `watermark` | dropdown | `false` | Add/suppress Alibaba watermark |
| `seed` | INT (-1–2147483647) | `-1` | Random seed. `-1` = random each run (omitted from request). |
| `retries` | INT (0–3) | `0` | Auto-retry on transient 429/5xx errors with exponential backoff |

#### Outputs

| Output | Type | Description |
|---|---|---|
| `images` | IMAGE | Batch tensor (B×H×W×3, float32, 0–1) |

#### Mode auto-detection

- No `image` connected → **text-to-image**
- `image` connected → **image editing / composition** (prompt + up to 9 input frames)
- `enable_sequential=true` → **image set generation** (coherent sequence)

#### Example workflows

**Text to image:**
```
[API Key] key_name=DASHSCOPE_API_KEY ──api_key──► [Wan Image Generate]
                    prompt = "A misty Japanese mountain temple at dawn, photorealistic"
                    model  = wan2.7-image-pro  size = 2K
                    ──images──► [Save Image (no workflow metadata)]
```

**Image editing:**
```
[Load Image] ──image──► [Wan Image Generate]
                prompt = "Convert to pencil sketch style, keep the composition"
                ──images──► [Preview Image]
```

**`.env` file:**
```
DASHSCOPE_API_KEY=sk-...
```

---

### `wan_video` — Wan Video Generate

Encapsulates four Wan 2.7 video generation modes in a single node. Mode is selected automatically based on which inputs are connected.

**Category:** `Ranomany/Alibaba`
**Dependencies:** none (Python stdlib only)
**API key env var:** `DASHSCOPE_API_KEY`

#### Mode auto-detection

| Connected inputs | Mode | Model |
|---|---|---|
| `prompt` only | **Text-to-video** | `wan2.7-t2v` |
| `first_frame` | **Image-to-video (i2v)** | `wan2.7-i2v-2026-04-25` |
| `first_frame` + `last_frame` | **First+last frame (r2v)** | `wan2.7-i2v-2026-04-25` |
| `first_clip` | **Video continuation** | `wan2.7-i2v-2026-04-25` |

#### Inputs

| Input | Type | Default | Notes |
|---|---|---|---|
| `prompt` | STRING | — | Video description. Required for t2v; optional for i2v/r2v/continuation. |
| `first_frame` | IMAGE | *(optional)* | Anchors the first frame. Triggers i2v or r2v mode. |
| `last_frame` | IMAGE | *(optional)* | Anchors the last frame. Only used with `first_frame` (r2v mode). |
| `first_clip` | VIDEO | *(optional)* | Source video to continue. Triggers continuation mode. |
| `api_key` | STRING (masked) | *(optional)* | Wire from `API Key` node, or leave blank to use env var / `.env` |
| `workspace_id` | STRING | *(optional)* | Singapore workspace ID. Leave blank for Beijing. |
| `negative_prompt` | STRING | *(optional)* | Content to exclude (max 500 chars) |
| `resolution` | dropdown | `1080P` | `1080P`, `720P` |
| `ratio` | dropdown | `16:9` | Aspect ratio — applies to t2v only. i2v/r2v/continuation follow the input image/clip. |
| `duration` | INT (2–15) | `5` | Output length in seconds |
| `prompt_extend` | dropdown | `true` | Let the model rewrite short prompts to improve quality |
| `watermark` | dropdown | `false` | Add/suppress Alibaba watermark |
| `seed` | INT (-1–2147483647) | `-1` | Random seed. `-1` = random each run. |
| `max_wait` | INT (60–1800) | `600` | Seconds before timing out |
| `poll_interval` | INT (5–60) | `15` | Seconds between status polls |

#### Outputs

| Output | Type | Description |
|---|---|---|
| `video` | VIDEO | Filepath dict. Wire to **Save Video** to write the MP4 to disk. |

#### Example workflows

**Text-to-video:**
```
[API Key] key_name=DASHSCOPE_API_KEY ──api_key──► [Wan Video Generate]
                    prompt     = "A lone surfer rides a massive wave at sunset, slow motion"
                    resolution = 1080P   ratio = 16:9   duration = 5
                    ──video──► [Save Video]
```

**Image-to-video:**
```
[Load Image] ──first_frame──► [Wan Video Generate]
                prompt = "The camera slowly pans to reveal the surrounding landscape"
                ──video──► [Save Video]
```

**First+last frame (r2v):**
```
[Load Image] ──first_frame──► [Wan Video Generate]
[Load Image] ──last_frame───►     prompt = "A smooth transition between the two scenes"
                                  ──video──► [Save Video]
```

**Video continuation:**
```
[Wan Video Generate] ──video──► [Wan Video Generate]  (wire to first_clip)
                                    prompt = "The character continues walking into the forest"
                                    ──video──► [Save Video]
```

---

### `wan_video_edit` — Wan Video Edit

Edit an existing video with a text instruction, optionally guided by reference images for style or character consistency.

**Category:** `Ranomany/Alibaba`
**Dependencies:** none (Python stdlib only)
**API key env var:** `DASHSCOPE_API_KEY`
**Model:** `wan2.7-videoedit`

#### Inputs

| Input | Type | Default | Notes |
|---|---|---|---|
| `prompt` | STRING | — | Edit instruction — e.g. `"Convert to claymation style"`, `"Make it rain"`. Required. |
| `video` | VIDEO | — | The video to edit. Required. |
| `reference_image_1` | IMAGE | *(optional)* | Reference image for style / character transfer |
| `reference_image_2` | IMAGE | *(optional)* | Additional reference (up to 4 total) |
| `reference_image_3` | IMAGE | *(optional)* | |
| `reference_image_4` | IMAGE | *(optional)* | |
| `api_key` | STRING (masked) | *(optional)* | Wire from `API Key` node, or leave blank to use env var / `.env` |
| `workspace_id` | STRING | *(optional)* | Singapore workspace ID. Leave blank for Beijing. |
| `negative_prompt` | STRING | *(optional)* | Content to exclude from the output |
| `resolution` | dropdown | `1080P` | `1080P`, `720P` |
| `ratio` | dropdown | `auto` | `auto` follows the input video's aspect ratio. Or pick a fixed ratio: `16:9`, `9:16`, `1:1`, `4:3`, `3:4`. |
| `duration` | INT (0–10) | `0` | Output duration in seconds. `0` = keep input video's duration. `2–10` to truncate. |
| `audio_setting` | dropdown | `auto` | `auto` = model decides audio treatment; `origin` = keep the original audio track |
| `prompt_extend` | dropdown | `true` | Let the model expand short prompts |
| `watermark` | dropdown | `false` | Add/suppress Alibaba watermark |
| `seed` | INT (-1–2147483647) | `-1` | Random seed |
| `max_wait` | INT (60–1800) | `600` | Seconds before timing out |
| `poll_interval` | INT (5–60) | `15` | Seconds between status polls |

#### Outputs

| Output | Type | Description |
|---|---|---|
| `video` | VIDEO | Filepath dict. Wire to **Save Video** to write the MP4 to disk. |

#### Example workflows

**Style transfer:**
```
[Wan Video Generate] ──video──► [Wan Video Edit]
                                    prompt = "Convert to claymation style, keep the motion"
                                    ──video──► [Save Video]
```

**Character-consistent edit with reference:**
```
[Load Video] ──video─────────────► [Wan Video Edit]
[Load Image] ──reference_image_1──►    prompt = "Replace the actor with this character"
                                        ──video──► [Save Video]
```

---

### `camera_angle` — Camera Angle

An interactive **3D camera-angle control** (Vue + Three.js GUI, ported from
`ComfyUI-qwenmultiangle` with industry-standard cinematography terminology). Drag the
azimuth ring, elevation arc, and distance handle — or type into the sliders — and the node
emits a prose instruction prompt for image-to-image **camera retargeting** that large
models (Gemini, GPT Image, Wan) parse reliably, plus the individual angle labels.

**Category:** `Ranomany/Utils`
**Dependencies:** none (the Three.js GUI is shipped pre-built in `web/camera_angle.bundle.js`)

#### Inputs

| Input | Type | Default | Notes |
|---|---|---|---|
| `horizontal_angle` | INT slider (0–360) | `0` | Azimuth |
| `vertical_angle` | INT slider (−30–60) | `0` | Elevation (the 3D handle is clamped to this range) |
| `zoom` | FLOAT slider (0–10) | `5.0` | Distance — higher = closer |
| `image` | IMAGE | *(optional)* | Shown on the plane inside the 3D scene **after the first run** |

#### Outputs

| Output | Type | Description |
|---|---|---|
| `prompt` | STRING | `Change the camera to a {shot} from a {vertical}, {horizontal} of the same subject. Preserve identity, materials, and lighting — only change the camera angle and framing.` |
| `horizontal` | STRING | e.g. `right side profile` |
| `vertical` | STRING | e.g. `slight high angle` |
| `shot_size` | STRING | e.g. `close-up` |

#### Taxonomy

| Axis | Zones |
|---|---|
| **Horizontal** (8) | front view · front-right three-quarter angle · right side profile · rear-right three-quarter angle · rear view · rear-left three-quarter angle · left side profile · front-left three-quarter angle |
| **Vertical** (6) | low-angle shot · slight low angle · eye-level shot · slight high angle · high-angle shot · overhead high-angle shot |
| **Shot size** (8) | extreme wide · wide · full · medium long · medium · close-up · extreme close-up · macro |

The 3D GUI is a single self-contained bundle (Three.js baked in — no external import). Its
Vue/TypeScript source lives in `nodes/camera_angle/gui/`; rebuild with
`cd nodes/camera_angle/gui && npm install && npm run build`, then copy `js/main.js` →
`web/camera_angle.bundle.js` and `js/assets/main.css` → `web/assets/main.css`.

---

### `camera_angle` — Camera Angle (Load Image)

Same 3D control as **Camera Angle**, but with a **built-in image picker** instead of an
IMAGE input port. It loads its own image (native All / Imported / Generated browser +
upload), shows it in the 3D scene **immediately** (no run required), and outputs the loaded
IMAGE/MASK alongside the camera prompt. The picker and the 3D widget both render in the
**app/run panel**.

**Category:** `Ranomany/Utils`
**Dependencies:** none

| Input | Type | Notes |
|---|---|---|
| `horizontal_angle` / `vertical_angle` / `zoom` | INT / INT / FLOAT | Same as Camera Angle |
| `image` | native image picker (`image_upload`) | Pick an input/output image or upload one; appears in the 3D scene at once |

| Output | Type | Description |
|---|---|---|
| `prompt`, `horizontal`, `vertical`, `shot_size` | STRING | Same as Camera Angle |
| `image` | IMAGE | The loaded image (B×H×W×3, float32, 0–1) |
| `mask` | MASK | Alpha-derived mask (zeros for images without alpha) |

---

### `load_latest_output` — Load Image (Edit Mode)

A **Load Image** node built for an iterative edit loop. Uses the native ComfyUI image
picker (All / Imported / Generated browser + upload) and outputs IMAGE/MASK. A
**refresh / newest** button and an automatic snap to the **newest output image** after every
run keep it pointed at the last generated image, so you can load → edit → regenerate → load
again without re-picking.

**Category:** `Ranomany/Utils`
**Dependencies:** none

| Input | Type | Notes |
|---|---|---|
| `image` | native image picker (`image_upload`) | Pick any input/output image, upload one, or let it auto-snap to the newest output |

| Output | Type | Description |
|---|---|---|
| `image` | IMAGE | The loaded image (B×H×W×3, float32, 0–1) |
| `mask` | MASK | Alpha-derived mask |

**Notes**
- The native inline image preview is hardcoded (in the frontend) to `node.type === "LoadImage"`,
  so this node renders its own `<img>` preview as a DOM widget that shows in the **app/run
  panel** (gated to app mode via CSS so the editor isn't double-previewed). Expose the
  `preview` widget in the app builder to show it.
- Auto-snap uses the `GET /ranomany/latest-output` route (registered by
  `nodes/load_latest_output/server.py`) to find the newest output file by modification time —
  the browser can't read mtimes on its own.

---

## Versioning

This repo is consumed by SHA pin from downstream Dockerfiles. There is **no semver, no tags, no `latest`**. To roll a downstream forward, bump the `RANOMANY_COMFYNODES_SHA` build arg and rebuild.

# Ranomany-ComfyNodes

Shared ComfyUI custom-node pack used across Ranomany projects.

**Layout** — one node per subdirectory under `nodes/`. Each subdir is a self-contained ComfyUI custom node that can be installed on its own by copying the directory into `custom_nodes/`. This lets each endpoint pick the subset it actually needs.

```
Ranomany-ComfyNodes/
├── README.md
├── manifest.yaml                # node_name -> {description, deps, version}
├── web/                         # JS extensions auto-loaded by ComfyUI frontend
│   └── save_video.js            # Inline video preview for Save Video node
└── nodes/
    ├── api_key/                 # Generic API key resolver (any provider)
    ├── gemini_image/            # Image generation / editing via Gemini
    ├── gemini_veo/              # Video generation via Veo + Save Video node
    ├── openai_image/            # Image generation / editing via OpenAI gpt-image-2
    └── save_image_no_meta/      # Save PNG without workflow metadata
```

---

## Installing into ComfyUI

Copy the subdirectory (or directories) you need into your ComfyUI `custom_nodes/` folder:

```bash
cp -r nodes/api_key         /path/to/ComfyUI/custom_nodes/
cp -r nodes/gemini_image    /path/to/ComfyUI/custom_nodes/
cp -r nodes/gemini_veo      /path/to/ComfyUI/custom_nodes/
cp -r nodes/save_image_no_meta /path/to/ComfyUI/custom_nodes/
```

Install dependencies:

```bash
pip install google-genai>=1.0.0   # required by gemini_image and gemini_veo
pip install openai>=1.0.0          # required by openai_image
pip install mutagen>=1.47.0        # optional — enables MP4 metadata embedding in Save Video
```

### Pinning by SHA in a Dockerfile

```dockerfile
ARG RANOMANY_COMFYNODES_SHA=<commit-sha>
RUN git clone https://github.com/EldadRan/Ranomany-ComfyNodes.git /tmp/cn && \
    cd /tmp/cn && git checkout "$RANOMANY_COMFYNODES_SHA" && \
    cp -r /tmp/cn/nodes/api_key         /comfyui/custom_nodes/ && \
    cp -r /tmp/cn/nodes/gemini_image    /comfyui/custom_nodes/ && \
    cp -r /tmp/cn/nodes/gemini_veo      /comfyui/custom_nodes/ && \
    cp -r /tmp/cn/nodes/openai_image    /comfyui/custom_nodes/ && \
    cp -r /tmp/cn/nodes/save_image_no_meta /comfyui/custom_nodes/ && \
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

## Versioning

This repo is consumed by SHA pin from downstream Dockerfiles. There is **no semver, no tags, no `latest`**. To roll a downstream forward, bump the `RANOMANY_COMFYNODES_SHA` build arg and rebuild.

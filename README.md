# Ranomany-ComfyNodes

Shared ComfyUI custom-node pack used across all Ranomany ComfyUI-on-RunPod endpoints (Flux2x and future projects).

**Layout** — one node per subdirectory under `nodes/`. Each subdir is a self-contained ComfyUI custom node that can be installed on its own by copying the directory into `/comfyui/custom_nodes/`. This lets each endpoint pick the subset it actually needs.

```
Ranomany-ComfyNodes/
├── README.md
├── manifest.yaml                # node_name -> {description, deps, version}
└── nodes/
    └── save_image_no_meta/
        ├── __init__.py          # registers the node
        └── node.py
```

## Installing into a ComfyUI image

Pin by SHA — never `latest`, never a branch, never a tag:

```dockerfile
ARG RANOMANY_COMFYNODES_SHA=<commit-sha>
RUN git clone https://github.com/<org>/Ranomany-ComfyNodes.git /tmp/cn && \
    cd /tmp/cn && git checkout "$RANOMANY_COMFYNODES_SHA" && \
    cp -r /tmp/cn/nodes/save_image_no_meta /comfyui/custom_nodes/
```

Pick whichever subdirs the endpoint needs by adding `cp` lines.

## Nodes

### `save_image_no_meta`

ComfyUI's stock `SaveImage` embeds the entire workflow JSON in PNG `tEXt` chunks. This leaks the workflow structure to anyone who downloads the image and bloats output. `SaveImageNoMeta` saves clean PNGs and embeds **only** the keys you explicitly pass via the `extra_metadata` input.

| Input             | Type    | Purpose |
|-------------------|---------|---------|
| `images`          | IMAGE   | Same as core SaveImage. |
| `filename_prefix` | STRING  | Same as core SaveImage. |
| `extra_metadata`  | STRING  | Optional JSON object. Each key/value pair is written as a PNG `tEXt` chunk. Examples: `{"seed": "12345", "model_used": "flux2-klein-4b-distilled"}`. Pass `""` or `"{}"` for fully clean output. |

The Flux2x handler typically passes `{"seed": ..., "model_used": ..., "workflow": ...}`.

## Versioning

This repo is consumed by SHA pin from downstream Dockerfiles. There is **no semver, no tags, no `latest`**. To roll a downstream forward, bump the `RANOMANY_COMFYNODES_SHA` build arg deliberately and rebuild.

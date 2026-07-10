# seedvr2_runpod — SeedVR2 image upscaler, RunPod serverless worker

GPU worker that upscales **one image per job** with the
[SeedVR2](https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler) diffusion upscaler
(vendored at a pinned commit — see `ARG SEEDVR2_COMMIT` in the Dockerfile). It is the
backend for the **SeedVR2 Upscale (RunPod)** node in Ranomany-ComfyNodes
(`nodes/seedvr_runpod/`), but any client that speaks the contract below works.

No ComfyUI runs here: the handler drives SeedVR2's standalone CLI entry points
in-process (`parse_arguments` / `download_weight` / `process_single_file`) and keeps the
DiT + VAE loaded across warm jobs via the CLI's own `runner_cache` (reloaded only when a
job requests a different model).

## Contract

`POST https://api.runpod.ai/v2/<ENDPOINT_ID>/run` with `Authorization: Bearer <RUNPOD_API_KEY>`:

```jsonc
{ "input": {
    "mode": "upscale",                                   // only supported mode
    "image": "<base64>",                                 // data-URI prefix tolerated
    "image_mime": "image/png",                           // informational
    "model": "seedvr2_ema_3b_fp8_e4m3fn.safetensors",    // default; see registry below
    "resolution": 1080,                                  // target short side
    "max_resolution": 0,                                 // longest-edge cap, 0 = unlimited
    "seed": 42,
    "color_correction": "wavelet",                       // lab|wavelet|wavelet_adaptive|hsv|adain|none
    "debug_level": 0                                     // 0 none | 1 handler logs | 2 + SeedVR2 debug
}}
```

Poll `GET /v2/<ENDPOINT_ID>/status/<job_id>` until `COMPLETED`; the worker's envelope is
in `output`:

```jsonc
// success
{ "status": "ok",
  "result": { "image": "<b64 png>", "mime_type": "image/png", "width": 1920, "height": 1080,
              "model_used": "...", "seed": 42, "elapsed_seconds": 21.4 },
  "logs": ["..."] }          // only when debug_level > 0

// failure (the job itself still COMPLETES — errors ride the envelope)
{ "status": "error", "error": "...", "type": "validation|internal", "logs": ["..."] }
```

Models: any DiT entry in the pinned repo's `src/utils/model_registry.py` —
`seedvr2_ema_{3b,7b,7b_sharp}` in `fp16` / `fp8_e4m3fn(_mixed_block35_fp16)` /
`Q8_0.gguf` / `Q4_K_M.gguf` variants. Auth is RunPod's platform key only; there is no
extra shared secret.

## Deploy

1. **Build & push** (or let CI do it — `.github/workflows/docker-publish.yml` builds this
   directory on every push that touches it and pushes to GHCR):

   ```bash
   docker build workers/seedvr2_runpod -t ghcr.io/<owner>/seedvr2-runpod-worker:latest
   docker push ghcr.io/<owner>/seedvr2-runpod-worker:latest
   ```

2. **Create a network volume** (RunPod → Storage), e.g. 30 GB, in the region you'll run in.
   Weights auto-download from HuggingFace (`numz/SeedVR2_comfyUI`) on the first job and
   land on the volume, so later cold starts skip the multi-GB download.

3. **Create the serverless endpoint** (RunPod → Serverless → New Endpoint):
   - Container image: `ghcr.io/<owner>/seedvr2-runpod-worker:latest` (make the GHCR
     package public, or add registry credentials).
   - Attach the network volume (mounts at `/runpod-volume` — the handler picks
     `/runpod-volume/models/SEEDVR2` automatically; override with `SEEDVR2_MODEL_DIR`).
   - GPU: 24 GB class (RTX 4090 / L4 / A5000) comfortably runs the default 3B fp8 model
     (~12–16 GB VRAM at 1080p); pick 48 GB (L40S/A6000) for 7B fp16 or very large outputs.
   - Execution timeout: ≥ 600 s (first-ever job also downloads weights).

4. **Point the ComfyUI node at it** — in the ComfyUI root `.env` (or environment):

   ```bash
   RUNPOD_API_KEY=...
   RUNPOD_ENDPOINT_ID=...
   ```

## Smoke test

```bash
# local CPU check of the envelope/validation path (no GPU, monkeypatch inference):
python -c "
import json, handler
handler._run_inference = lambda i, o, p, debug: __import__('shutil').copyfile(i, o)
print(json.dumps(handler.handler(json.load(open('test_input.json')))
                 , default=str)[:300])"

# against the live endpoint:
curl -s -X POST "https://api.runpod.ai/v2/$RUNPOD_ENDPOINT_ID/run" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" -H "Content-Type: application/json" \
  -d @test_input.json
```

## Env vars

| var                 | default                                             | purpose                        |
|---------------------|-----------------------------------------------------|--------------------------------|
| `SEEDVR2_DIR`       | `/app/SeedVR2`                                      | vendored repo location         |
| `SEEDVR2_MODEL_DIR` | `/runpod-volume/models/SEEDVR2` (if volume mounted) | where weights download/persist |

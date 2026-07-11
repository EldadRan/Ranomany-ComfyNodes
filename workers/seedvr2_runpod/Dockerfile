# SeedVR2 image-upscale worker for RunPod serverless.
# Weights (7B fp16 DiT + shared VAE) are BAKED into the image at build time (see
# bake_weights.py), so the worker needs NO network volume and can run in any
# datacenter that has GPU availability. SEEDVR2_MODEL_DIR points the runtime at the
# baked weights (the handler's _model_dir() honors this env var first).

FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

# Pinned SeedVR2 commit — the handler drives this exact source's CLI entry points.
ARG SEEDVR2_COMMIT=4490bd1f482e026674543386bb2a4d176da245b9

ENV SEEDVR2_DIR=/app/SeedVR2 \
    SEEDVR2_MODEL_DIR=/app/models/SEEDVR2 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler.git "$SEEDVR2_DIR" \
 && git -C "$SEEDVR2_DIR" checkout "$SEEDVR2_COMMIT" \
 && rm -rf "$SEEDVR2_DIR/.git"

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r "$SEEDVR2_DIR/requirements.txt" -r requirements.txt

# Bake the weights into the image (its own layer, so editing handler.py below does
# not re-download multi-GB weights on rebuild). ~14 GB DiT + ~0.3 GB VAE.
COPY bake_weights.py ./
RUN python bake_weights.py

COPY handler.py test_input.json ./

# Build-time sanity check: the handler must import without a GPU
# (the SeedVR2/torch import inside it is lazy, so this stays cheap).
RUN python -c "import handler"

CMD ["python", "-u", "handler.py"]

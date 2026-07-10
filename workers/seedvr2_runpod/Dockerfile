# SeedVR2 image-upscale worker for RunPod serverless.
# Weights are NOT baked in — they auto-download to SEEDVR2_MODEL_DIR on the first
# job (mount a network volume at /runpod-volume so they survive cold starts).

FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

# Pinned SeedVR2 commit — the handler drives this exact source's CLI entry points.
ARG SEEDVR2_COMMIT=4490bd1f482e026674543386bb2a4d176da245b9

ENV SEEDVR2_DIR=/app/SeedVR2 \
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

COPY handler.py test_input.json ./

# Build-time sanity check: the handler must import without a GPU
# (the SeedVR2/torch import inside it is lazy, so this stays cheap).
RUN python -c "import handler"

CMD ["python", "-u", "handler.py"]

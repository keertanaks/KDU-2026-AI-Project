# hf_space/Dockerfile
# Harmony Project 3 — inference server image for HuggingFace Spaces.
# Uses llama-cpp-python with GGUF model (base-q8.gguf + adapter.gguf).
# Runs on free CPU tier (16 GB RAM) — 8 GB GGUF fits with room to spare.

FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/tmp/hf_cache \
    HF_HUB_ENABLE_HF_TRANSFER=1 \
    CMAKE_ARGS="-DGGML_BLAS=OFF -DGGML_CUDA=OFF"

# llama-cpp-python compiles from source — needs cmake + C++ compiler
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        git \
        && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 7860
CMD ["python", "app.py"]

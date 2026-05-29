# hf_space/Dockerfile
# Harmony Project 3 — inference server image for HuggingFace Spaces.
# Targets HF Space SDK=docker; works on both CPU Basic (free) and T4 (paid)
# hardware tiers thanks to the CUDA-availability check in app.py.

FROM python:3.10-slim

# Avoid pyc files and ensure stdout/stderr are unbuffered (so HF logs are live)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/tmp/hf_cache \
    TRANSFORMERS_CACHE=/tmp/hf_cache

# System deps required by some wheels (bitsandbytes, sentencepiece protobuf compile)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps in their own layer so app code changes don't bust the cache
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the app
COPY app.py .

# HF Spaces convention: serve on port 7860, host 0.0.0.0
EXPOSE 7860
CMD ["python", "app.py"]

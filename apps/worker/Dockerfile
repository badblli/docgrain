FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

RUN apt-get update \
    && apt-get install --no-install-recommends -y libgl1 libglib2.0-0 libxcb1 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Docling uses PyTorch for layout analysis. Pin the CPU wheel so a local
# development worker does not download CUDA runtimes it cannot use.
COPY apps/worker/pyproject.toml /srv/apps/worker/pyproject.toml
RUN mkdir -p /srv/apps/worker/docgrain_worker \
    && touch /srv/apps/worker/docgrain_worker/__init__.py
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision \
    && pip install --no-cache-dir -e /srv/apps/worker

# Keep application code in a separate layer so source edits reuse the heavy
# Torch and Docling dependency layer above.
COPY apps/worker/docgrain_worker /srv/apps/worker/docgrain_worker

CMD ["python", "-m", "docgrain_worker.main"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

RUN apt-get update \
    && apt-get install --no-install-recommends -y libgl1 libglib2.0-0 libxcb1 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY apps/worker /srv/apps/worker
# Docling uses PyTorch for layout analysis. Pin the CPU wheel so a local
# development worker does not download CUDA runtimes it cannot use.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision \
    && pip install --no-cache-dir -e /srv/apps/worker

CMD ["python", "-m", "docgrain_worker.main"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV DOCGRAIN_OCR_MODEL_DIR=/opt/docgrain/easyocr OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
WORKDIR /srv

RUN apt-get update \
    && apt-get install --no-install-recommends -y libgl1 libglib2.0-0 libxcb1 libxext6 libxrender1 \
        tesseract-ocr tesseract-ocr-tur tesseract-ocr-deu tesseract-ocr-rus tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Docling uses PyTorch for layout analysis. Pin the CPU wheel so a local
# development worker does not download CUDA runtimes it cannot use.
COPY apps/worker/pyproject.toml /srv/apps/worker/pyproject.toml
COPY apps/api/pyproject.toml /srv/apps/api/pyproject.toml
COPY packages/domain/pyproject.toml /srv/packages/domain/pyproject.toml
COPY packages/evaluation/pyproject.toml /srv/packages/evaluation/pyproject.toml
COPY packages/records/pyproject.toml /srv/packages/records/pyproject.toml
COPY packages/access /srv/packages/access
COPY packages/records/taxonomy.json /srv/packages/records/taxonomy.json
RUN mkdir -p /srv/packages/evaluation/docgrain_eval     && touch /srv/packages/evaluation/docgrain_eval/__init__.py     && mkdir -p /srv/packages/records/docgrain_records     && touch /srv/packages/records/docgrain_records/__init__.py     && mkdir -p /srv/apps/worker/docgrain_worker \
    && touch /srv/apps/worker/docgrain_worker/__init__.py \
    && mkdir -p /srv/apps/api/docgrain_api \
    && touch /srv/apps/api/docgrain_api/__init__.py \
    && mkdir -p /srv/packages/domain/docgrain_domain \
    && touch /srv/packages/domain/docgrain_domain/__init__.py
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision \
    && pip install --no-cache-dir -e /srv/packages/domain -e /srv/packages/evaluation -e /srv/packages/records -e /srv/packages/access -e /srv/apps/api -e /srv/apps/worker

# Keep application code in a separate layer so source edits reuse the heavy
# Torch and Docling dependency layer above.
COPY apps/worker/docgrain_worker /srv/apps/worker/docgrain_worker
COPY apps/api/docgrain_api /srv/apps/api/docgrain_api
COPY packages/domain/docgrain_domain /srv/packages/domain/docgrain_domain
COPY packages/evaluation /srv/packages/evaluation
COPY packages/records /srv/packages/records

# Fetch verified CRAFT/Latin checkpoints at build time; runtime never downloads OCR weights.
RUN python -m docgrain_worker.ocr --download

CMD ["python", "-m", "docgrain_worker.main"]

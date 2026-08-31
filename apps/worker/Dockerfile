FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY apps/worker /srv/apps/worker
RUN pip install --no-cache-dir -e /srv/apps/worker

CMD ["python", "-m", "docgrain_worker.main"]

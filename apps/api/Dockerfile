FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY packages/domain /srv/packages/domain
COPY apps/api /srv/apps/api

RUN pip install --no-cache-dir -e /srv/packages/domain -e /srv/apps/api

EXPOSE 8000
CMD ["uvicorn", "docgrain_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

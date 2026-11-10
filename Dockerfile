# syntax=docker/dockerfile:1
# UniSlot API release image (Lab 10, bonus 5). Built by .github/workflows/release-image.yml
# after every green CI run on main and published to ghcr.io, tagged with the commit SHA.
# Without UNISLOT_DATABASE_URL the API serves the in-memory demo store, as it does locally;
# with it, the API uses a migrated PostgreSQL (docs/deployment/render.md).
# Python 3.12 as on the public demo (render.yaml); the patch release and the Debian base
# float to receive security fixes. For a byte-identical rebuild, pin the image by digest.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UNISLOT_EXPORT_OPENAPI=0 \
    UNISLOT_DEMO_AUTH=0

WORKDIR /app

# Dependencies first: this layer is reused while requirements.txt does not change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only the application code: no tests, docs, secrets or local data in the image.
COPY src/ ./src/

# The API process needs no root privileges inside the container.
RUN useradd --create-home --uid 10001 unislot
USER unislot

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status != 200)"]

CMD ["uvicorn", "api.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]

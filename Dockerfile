FROM python:3.11-slim

WORKDIR /app

COPY . /app
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /app/interpreters/user
ENV PYTHONUNBUFFERED=1

# Set to "dockerhub" only for the Docker Hub image, which then logs a
# "this image has moved to GHCR" notice at startup. Declared last so the
# Docker Hub and GHCR builds share every layer above.
ARG REGISTRY_NOTICE=""
ENV REGISTRY_NOTICE=${REGISTRY_NOTICE}

CMD ["python", "main.py"]

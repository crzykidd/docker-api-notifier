FROM python:3.11-alpine

WORKDIR /app

# Pick up Alpine security fixes the base image doesn't carry yet.
RUN apk upgrade --no-cache

COPY . /app
# Install with a current pip, then remove the packaging tooling (pip,
# setuptools, wheel): the notifier never uses it at runtime, and it carries
# the base image's Python CVEs. pip goes last so it can uninstall
# itself. The setuptools wheel ensurepip bundles (only used to bootstrap a
# venv) goes too.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y setuptools wheel \
    && pip uninstall -y pip \
    && rm -f /usr/local/lib/python3.11/ensurepip/_bundled/setuptools-*.whl \
    && mkdir -p /app/interpreters/user
ENV PYTHONUNBUFFERED=1

# /healthz endpoint (set HEALTH_PORT=0 to disable; the probe then passes).
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "healthcheck.py"]

CMD ["python", "main.py"]

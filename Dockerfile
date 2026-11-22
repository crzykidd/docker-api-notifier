FROM python:3.11-slim

WORKDIR /app

COPY . /app
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /app/interpreters/user
ENV PYTHONUNBUFFERED=1

# /healthz endpoint (set HEALTH_PORT=0 to disable; the probe then passes).
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "healthcheck.py"]

CMD ["python", "main.py"]

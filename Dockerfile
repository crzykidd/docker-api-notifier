FROM python:3.11-slim

WORKDIR /app

COPY . /app
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /app/interpreters/user
ENV PYTHONUNBUFFERED=1
CMD ["python", "main.py"]
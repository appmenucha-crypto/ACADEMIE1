# -------- Build stage --------
FROM python:3.11-slim AS builder

WORKDIR /app
COPY app/requirements.txt .

RUN pip install --no-cache-dir --user -r requirements.txt

# -------- Production stage --------
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    postgresql-client \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /root/.local /root/.local
COPY app/ .

ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/app
ENV DJANGO_SETTINGS_MODULE=config.settings

EXPOSE ${PORT:-8000}

RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
CMD []
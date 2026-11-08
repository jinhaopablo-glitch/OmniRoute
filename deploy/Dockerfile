# Imagen única para los dos procesos de PUAVI AI (worker de agentes y ejecutor).
# Cada proceso recibe SOLO sus propias variables de entorno (ver docs/despliegue.md).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PUAVI_BRAND_FILE=/app/brand/puavi-brand.md

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/puavi backend/puavi
COPY brand brand
RUN pip install ./backend

# Usuario sin privilegios.
RUN useradd --create-home --uid 10001 puavi
USER puavi

# Por defecto, el worker de agentes. El ejecutor se arranca con:
#   python -m puavi.executor
CMD ["python", "-m", "puavi.worker"]

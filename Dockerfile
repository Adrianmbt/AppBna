# Imagen del backend público (portal del paciente) para Render o Railway.
# Se construye desde la raíz del repositorio: el contexto debe contener app/
# y requirements.txt, y el paquete tiene que seguir llamándose app/ porque los
# imports son `from app...`.
#
#   docker build -t bnasalud-api .
#   docker run -p 8000:8000 --env-file .env bnasalud-api
#
# La plataforma inyecta $PORT y el CMD lo respeta sin configuración extra.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ENVIRONMENT=production

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

# Render/Railway inyectan $PORT; en local cae a 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import supabase
from app.core.scheduler import detener_programador, iniciar_programador
from app.api.v1.endpoints.citas import router as citas_router
from app.api.v1.endpoints.rrhh import router as rrhh_router
from app.api.v1.endpoints.farmacia import router as farmacia_router
from app.api.v1.endpoints.centros import router as centros_router
from app.api.v1.endpoints.especialidades import router as especialidades_router
from app.api.v1.endpoints.pacientes import router as pacientes_router
from app.api.v1.endpoints.consultas import router as consultas_router
from app.api.v1.endpoints.emergencias import router as emergencias_router
from app.api.v1.endpoints.estudios import router as estudios_router
from app.api.v1.endpoints.rag import router as rag_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.cola import router as cola_router
from app.api.v1.endpoints.admin import router as admin_router
from app.api.v1.endpoints.panel import router as panel_router

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Fase 5: tarea programada de recordatorios de cita (cada hora).
    # Se desactiva con ENABLE_SCHEDULER=false en plataformas sin proceso vivo.
    if settings.ENABLE_SCHEDULER:
        iniciar_programador()
    yield
    if settings.ENABLE_SCHEDULER:
        detener_programador()


app = FastAPI(
    title="Sistema de Salud Barcelona - API Backend",
    description="Backend para la gestión de citas, historias clínicas, emergencias, farmacia, talento humano y motor RAG",
    version="1.0.0",
    lifespan=lifespan,
)

# Configuración de CORS — en producción, CORS_ORIGINS="https://tu-frontend.vercel.app"
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origenes_cors or ["*"],
    allow_origin_regex=settings.CORS_ORIGIN_REGEX.strip() or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health")
def health():
    """Estado del servicio y de la conexión a la base de datos."""
    try:
        supabase.table("clinicas").select("id").limit(1).execute()
        db_estado = "ok"
    except Exception:
        db_estado = "error"
    return {
        "status": "online",
        "sistema": "Salud Barcelona Municipal",
        "version": "1.0.0",
        "entorno": settings.ENVIRONMENT,
        "base_de_datos": db_estado,
    }


@app.get("/")
def raiz():
    """Respuesta de cortesía para sondas de la plataforma y para GET /."""
    return {
        "servicio": settings.PROJECT_NAME,
        "estado": "online",
        "documentacion": "/docs",
        "salud": "/api/v1/health",
    }


# Registrar los routers de los módulos
app.include_router(citas_router, prefix="/api/v1/citas", tags=["Citas Médicas"])
app.include_router(rrhh_router, prefix="/api/v1/rrhh", tags=["Talento Humano"])
app.include_router(farmacia_router, prefix="/api/v1/farmacia", tags=["Farmacia"])
app.include_router(centros_router, prefix="/api/v1/centros", tags=["Centros de Salud"])
app.include_router(especialidades_router, prefix="/api/v1/especialidades", tags=["Especialidades"])
app.include_router(pacientes_router, prefix="/api/v1/pacientes", tags=["Pacientes"])
app.include_router(consultas_router, prefix="/api/v1/consultas", tags=["Consultas"])
app.include_router(emergencias_router, prefix="/api/v1/emergencias", tags=["Emergencias"])
app.include_router(estudios_router, prefix="/api/v1/estudios", tags=["Estudios / OCR"])
app.include_router(rag_router, prefix="/api/v1/rag", tags=["RAG / Asistente"])
app.include_router(auth_router, prefix="/api/v1/auth", tags=["Autenticación"])
app.include_router(cola_router, prefix="/api/v1/cola", tags=["Cola de Pacientes"])
app.include_router(admin_router, prefix="/api/v1/admin", tags=["Administración"])
app.include_router(panel_router, prefix="/api/v1/panel", tags=["Panel Institucional"])

# Servir el frontend React (build de Vite en frontend/dist/) solo si existe.
# En el despliegue el frontend va por separado en Vercel, así que estos montajes
# no se activan; se conservan para el uso local (backend + build en un solo proceso).
DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=DIST_DIR), name="static")
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="frontend")

# Maquetas estáticas: solo si el directorio existe (no se copia a la imagen Docker).
MAQUETAS_DIR = Path(__file__).resolve().parent.parent / "frontend" / "maquetas"
if MAQUETAS_DIR.is_dir():
    app.mount("/maquetas", StaticFiles(directory=MAQUETAS_DIR, html=True), name="maquetas")

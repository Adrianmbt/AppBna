from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import exigir_staff
from app.api.v1.errors import db_fail
from app.core.database import supabase
from app.schemas.schemas import EmergenciaCreate, EmergenciaResponse

router = APIRouter(tags=["Emergencias"])


def _a_emergencia(fila: dict) -> EmergenciaResponse:
    return EmergenciaResponse(
        id=fila["id"],
        paciente_id=fila.get("paciente_id"),
        centro_salud=fila.get("centro_salud", ""),
        nivel_triaje=fila.get("nivel_triaje", 3),
        descripcion=fila.get("descripcion", ""),
        estado=fila.get("estado", "en_atencion"),
        created_at=fila.get("created_at"),
    )


@router.post("", response_model=EmergenciaResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=EmergenciaResponse, status_code=status.HTTP_201_CREATED)
def registrar_emergencia(
    payload: EmergenciaCreate,
    _: dict = Depends(exigir_staff),
) -> EmergenciaResponse:
    """Registra una emergencia en la cola de triaje."""
    if payload.paciente_id:
        try:
            existe = (
                supabase.table("historias_clinicas")
                .select("id")
                .eq("id", payload.paciente_id)
                .execute()
                .data
            )
        except Exception:
            db_fail("validar al paciente")
        if not existe:
            from app.api.v1.errors import not_found

            not_found("Paciente")

    registro = {
        "paciente_id": payload.paciente_id,
        "centro_salud": payload.centro_salud,
        "nivel_triaje": payload.nivel_triaje,
        "descripcion": payload.descripcion,
        "estado": "en_atencion",
    }
    try:
        creado = supabase.table("emergencias").insert(registro).execute()
    except Exception:
        db_fail("registrar la emergencia")
    return _a_emergencia(creado.data[0])


@router.get("", response_model=List[EmergenciaResponse])
@router.get("/", response_model=List[EmergenciaResponse])
def cola_emergencias(
    centro_salud: Optional[str] = Query(default=None, description="Filtrar por centro"),
    estado: Optional[str] = Query(default=None, description="Filtrar por estado (en_atencion, finalizada...)"),
    _: dict = Depends(exigir_staff),
) -> List[EmergenciaResponse]:
    """Cola de emergencias ordenada por gravedad (triaje 1 = crítico primero)."""
    try:
        query = supabase.table("emergencias").select("*")
        if centro_salud:
            query = query.eq("centro_salud", centro_salud)
        if estado:
            query = query.eq("estado", estado)
        filas = query.order("nivel_triaje").order("created_at").execute().data or []
    except Exception:
        db_fail("cargar la cola de emergencias")
    return [_a_emergencia(f) for f in filas]

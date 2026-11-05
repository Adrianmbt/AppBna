from typing import List, Optional

from fastapi import APIRouter, Query

from app.api.v1.errors import db_fail
from app.core.database import supabase
from app.schemas.schemas import EspecialidadResponse

router = APIRouter(tags=["Especialidades"])


def _serializar(fila: dict) -> EspecialidadResponse:
    return EspecialidadResponse(
        id=fila.get("id"),
        nombre=fila.get("nombre", ""),
        descripcion=fila.get("descripcion", "") or "",
        icono=fila.get("icono") or "stethoscope",
    )


def _especialidades_del_centro(centro_id: int) -> List[EspecialidadResponse]:
    """Especialidades con personal médico asignado a una clínica."""
    try:
        personal = (
            supabase.table("personal")
            .select("especialidad")
            .eq("clinica_id", centro_id)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("consultar las especialidades del centro")
    nombres = {p.get("especialidad") for p in personal if p.get("especialidad")}
    if not nombres:
        return []
    try:
        filas = (
            supabase.table("especialidades")
            .select("*")
            .in_("nombre", sorted(nombres))
            .order("id")
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("cargar las especialidades")
    return [_serializar(f) for f in filas]


@router.get("", response_model=List[EspecialidadResponse])
@router.get("/", response_model=List[EspecialidadResponse])
def listar_especialidades(
    centro_id: Optional[int] = Query(default=None, description="Filtro opcional por centro de salud"),
) -> List[EspecialidadResponse]:
    """Lista las especialidades de la red municipal (opcionalmente filtradas por centro)."""
    if centro_id is not None:
        return _especialidades_del_centro(centro_id)
    try:
        filas = supabase.table("especialidades").select("*").order("id").execute().data or []
    except Exception:
        db_fail("cargar las especialidades")
    return [_serializar(f) for f in filas]

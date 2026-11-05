from datetime import date
from typing import Dict, List, Tuple

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import exigir_roles
from app.api.v1.errors import db_fail, fail, not_found
from app.core.database import supabase
from app.schemas.schemas import (
    AsignarTurnoSchema,
    DisponibilidadResponseSchema,
    PersonalDetalleSchema,
    TurnoResumenSchema,
)

router = APIRouter(tags=["Talento Humano"])

# Definición visual de cada turno por status del personal.
ESTADO_TURNOS: List[Tuple[str, str, str]] = [
    ("EN_GUARDIA", "Guardia 24h", "08:00 - 08:00"),
    ("DISPONIBLE", "Disponibles", "08:00 - 16:00"),
]


def _a_personal(fila: dict) -> PersonalDetalleSchema:
    return PersonalDetalleSchema(
        personal_id=fila["id"],
        nombre=f"{fila.get('nombre', '')} {fila.get('apellido', '')}".strip(),
        cargo=fila.get("cargo", ""),
        especialidad=fila.get("especialidad"),
        telefono=fila.get("telefono"),
        status=fila.get("status", "DISPONIBLE"),
    )


@router.get("/disponibilidad", response_model=DisponibilidadResponseSchema)
def obtener_disponibilidad_personal(
    clinica_id: int = Query(..., description="ID del centro de salud"),
    fecha: date = Query(default=date.today(), description="Fecha de consulta"),
    _: dict = Depends(exigir_roles("superusuario")),
) -> DisponibilidadResponseSchema:
    """Disponibilidad de personal de una clínica, agrupada por turno."""
    try:
        clinica = (
            supabase.table("clinicas").select("id").eq("id", clinica_id).execute().data
        )
    except Exception:
        db_fail("validar la clínica")
    if not clinica:
        not_found("Clínica")

    try:
        filas = (
            supabase.table("personal")
            .select("*")
            .eq("clinica_id", clinica_id)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("consultar el personal")

    por_estado: Dict[str, list] = {}
    for p in filas:
        por_estado.setdefault(p.get("status", "DISPONIBLE"), []).append(p)

    turnos: List[TurnoResumenSchema] = []
    total_guardia = 0
    for estado, nombre, horario in ESTADO_TURNOS:
        grupo = por_estado.get(estado, [])
        if not grupo:
            continue
        if estado == "EN_GUARDIA":
            total_guardia = len(grupo)
        turnos.append(
            TurnoResumenSchema(
                turno=nombre,
                horario=horario,
                personal=[_a_personal(p) for p in grupo],
            )
        )

    return DisponibilidadResponseSchema(
        clinica_id=clinica_id,
        fecha=fecha,
        total_personal_guardia=total_guardia,
        turnos=turnos,
    )


@router.post("/asignar-turno", status_code=status.HTTP_201_CREATED)
def asignar_turno_personal(
    payload: AsignarTurnoSchema,
    _: dict = Depends(exigir_roles("superusuario")),
) -> dict:
    """Asigna un turno a un miembro del personal y lo marca en guardia."""
    try:
        persona = (
            supabase.table("personal")
            .select("id, nombre, apellido")
            .eq("id", payload.personal_id)
            .execute()
            .data
        )
    except Exception:
        db_fail("validar al personal")
    if not persona:
        not_found("Miembro del personal")

    try:
        turno = (
            supabase.table("turnos")
            .select("id, nombre")
            .eq("id", payload.turno_id)
            .execute()
            .data
        )
    except Exception:
        db_fail("validar el turno")
    if not turno:
        not_found("Turno")

    registro = {
        "personal_id": payload.personal_id,
        "clinica_id": payload.clinica_id,
        "turno_id": payload.turno_id,
        "fecha_asignacion": payload.fecha_asignacion.isoformat(),
        "observaciones": payload.observaciones,
    }
    try:
        creado = supabase.table("personal_turnos").insert(registro).execute()
        supabase.table("personal").update({"status": "EN_GUARDIA"}).eq(
            "id", payload.personal_id
        ).execute()
    except Exception:
        db_fail("asignar el turno")

    nombre = f"{persona[0].get('nombre', '')} {persona[0].get('apellido', '')}".strip()
    return {
        "message": "Turno asignado exitosamente",
        "data": {
            "id": creado.data[0]["id"],
            "personal_id": payload.personal_id,
            "nombre": nombre,
            "turno": turno[0].get("nombre", ""),
            "clinica_id": payload.clinica_id,
            "fecha_asignacion": payload.fecha_asignacion.isoformat(),
        },
    }

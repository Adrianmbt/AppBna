"""Panel de administración (Fase 4): trazabilidad completa de recetas y resumen."""
from datetime import date
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends

from app.api.v1.deps import exigir_roles
from app.api.v1.errors import db_fail
from app.core.database import supabase

router = APIRouter(tags=["Administración"])


def _nombre_personal(nombres: Dict[int, str], persona_id: Optional[int]) -> str:
    if not persona_id:
        return ""
    return nombres.get(persona_id, "")


def _nombres_personal(ids: List[int]) -> Dict[int, str]:
    ids_validos = [i for i in ids if i]
    if not ids_validos:
        return {}
    try:
        filas = (
            supabase.table("personal")
            .select("id, nombre, apellido")
            .in_("id", ids_validos)
            .execute()
            .data
            or []
        )
    except Exception:
        return {}
    return {
        p["id"]: f"{p.get('nombre', '')} {p.get('apellido', '')}".strip()
        for p in filas
    }


@router.get("/bitacora")
def consultar_bitacora(
    accion: Optional[str] = None,
    username: Optional[str] = None,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    limite: int = 100,
    _: dict = Depends(exigir_roles("superusuario")),
) -> dict:
    """Bitácora de acciones sensibles con filtros opcionales (Fase 7)."""
    limite = max(1, min(limite, 300))
    try:
        query = supabase.table("bitacora_acciones").select("*")
        if accion:
            query = query.eq("accion", accion)
        if username:
            query = query.ilike("username", f"%{username}%")
        if desde:
            query = query.gte("creado_en", f"{desde.isoformat()}T00:00:00")
        if hasta:
            query = query.lte("creado_en", f"{hasta.isoformat()}T23:59:59")
        filas = (
            query.order("creado_en", desc=True)
            .limit(limite)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("consultar la bitácora")

    return {
        "registros": [
            {
                "id": r["id"],
                "username": r.get("username") or "",
                "rol": r.get("rol") or "",
                "usuario_id": r.get("usuario_id"),
                "accion": r.get("accion", ""),
                "entidad": r.get("entidad") or "",
                "entidad_id": r.get("entidad_id") or "",
                "detalle": r.get("detalle") or "",
                "creado_en": str(r.get("creado_en") or "")[:19],
            }
            for r in filas
        ]
    }


@router.get("/trazabilidad")
def trazabilidad_recetas(
    _: dict = Depends(exigir_roles("superusuario")),
) -> dict:
    """Línea de tiempo completa por receta: consulta → despacho → entrega → recepción."""
    try:
        recetas = (
            supabase.table("recetas")
            .select("*")
            .order("id", desc=True)
            .limit(200)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("consultar las recetas")

    if not recetas:
        return {"recetas": []}

    ids_recetas = [r["id"] for r in recetas]
    ids_consulta = [r["consulta_id"] for r in recetas if r.get("consulta_id")]

    despachos = {}
    try:
        filas = (
            supabase.table("despacho_registros")
            .select("*")
            .in_("receta_id", ids_recetas)
            .execute()
            .data
            or []
        )
        for d in filas:
            despachos.setdefault(d["receta_id"], []).append(d)
    except Exception:
        despachos = {}

    consultas = {}
    if ids_consulta:
        try:
            filas = (
                supabase.table("consultas")
                .select("id, comprobante_ref, created_at")
                .in_("id", ids_consulta)
                .execute()
                .data
                or []
            )
        except Exception:
            filas = []
        consultas = {c["id"]: c for c in filas}

    persona_ids = {
        p
        for r in recetas
        for p in (
            r.get("entregada_por_id"),
            *(d.get("despachado_por") for d in despachos.get(r["id"], [])),
        )
        if p
    }
    nombres = _nombres_personal(list(persona_ids))

    resultado = []
    for r in recetas:
        despacho = despachos.get(r["id"], [])
        consulta = consultas.get(r.get("consulta_id"))
        resultado.append(
            {
                "id": r["id"],
                "codigo_receta": r.get("codigo_receta", ""),
                "paciente_cedula": r.get("paciente_cedula", ""),
                "paciente_nombre": r.get("paciente_nombre", ""),
                "estado": r.get("estado", ""),
                "medico": r.get("medico", ""),
                "fecha_emision": str(r.get("fecha_emision") or "")[:19],
                "consulta_comprobante": consulta.get("comprobante_ref") if consulta else "",
                "consulta_fecha": str(consulta.get("created_at") or "")[:19] if consulta else "",
                "despachado_por": (
                    _nombre_personal(nombres, despacho[0].get("despachado_por"))
                    if despacho
                    else ""
                ),
                "despachado_at": str(despacho[0].get("fecha_despacho") or "")[:19]
                if despacho
                else "",
                "despachos": len(despacho),
                "entregado_por": _nombre_personal(nombres, r.get("entregada_por_id")),
                "entregado_at": str(r.get("entregada_at") or "")[:19],
                "recibido_at": str(r.get("recibida_at") or "")[:19],
                "recibida_paciente_id": str(r.get("recibida_paciente_id") or ""),
            }
        )
    return {"recetas": resultado}


@router.get("/resumen")
def resumen_operativo(
    _: dict = Depends(exigir_roles("superusuario")),
) -> dict:
    """Indicadores operativos del día para el panel de administración."""
    hoy = date.today().isoformat()
    try:
        recetas = supabase.table("recetas").select("id, estado, fecha_emision").execute().data or []
        citas_hoy = (
            supabase.table("citas").select("id").eq("fecha_cita", hoy).execute().data or []
        )
        consultas_hoy = (
            supabase.table("consultas").select("id").gte("created_at", f"{hoy}T00:00:00").execute().data or []
        )
        cola_espera = (
            supabase.table("cola_pacientes").select("id").eq("estado", "EN_ESPERA").execute().data or []
        )
        despachos = supabase.table("receta_detalles").select("medicamento_id, cantidad_despachada").execute().data or []
    except Exception:
        db_fail("consultar los indicadores")

    por_estado: Dict[str, int] = {}
    for r in recetas:
        estado = r.get("estado", "PENDIENTE")
        por_estado[estado] = por_estado.get(estado, 0) + 1

    top_medicamentos = {}
    ids_medicamento = [d["medicamento_id"] for d in despachos if d.get("medicamento_id")]
    nombres_med = {}
    if ids_medicamento:
        try:
            inventario = (
                supabase.table("inventario_medicamentos")
                .select("id, nombre")
                .in_("id", set(ids_medicamento))
                .execute()
                .data
                or []
            )
        except Exception:
            inventario = []
        nombres_med = {m["id"]: m.get("nombre", "") for m in inventario}
    for d in despachos:
        if d.get("medicamento_id"):
            nombre = nombres_med.get(d["medicamento_id"], "Desconocido")
            top_medicamentos[nombre] = top_medicamentos.get(nombre, 0) + (
                d.get("cantidad_despachada") or 0
            )

    return {
        "fecha": hoy,
        "citas_hoy": len(citas_hoy),
        "consultas_hoy": len(consultas_hoy),
        "cola_espera": len(cola_espera),
        "recetas_por_estado": por_estado,
        "top_medicamentos": sorted(
            top_medicamentos.items(), key=lambda x: x[1], reverse=True
        )[:5],
    }
from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import exigir_paciente, exigir_paciente_o_staff, exigir_roles
from app.api.v1.errors import db_fail, fail, not_found
from app.core.bitacora import registrar_accion
from app.core.database import supabase
from app.core.notificaciones import notificar_receta_entregada
from app.schemas.schemas import (
    DespacharRecetaRequestSchema,
    InventarioItemSchema,
    RecetaDetalleItemSchema,
    RecetaEntregarRequestSchema,
    RecetaResponseSchema,
)

router = APIRouter(tags=["Farmacia"])

# Ciclo de entrega: PENDIENTE → DESPACHADA → ENTREGADA → RECIBIDA
# jefe_farmacia: encargado del módulo (despacho + gestión del stock).
ROLES_FARMACIA = ("jefe_farmacia", "farmaceutico", "superusuario")
# Gestión de existencias (inventario/alertas): exclusiva de la jefatura.
ROLES_STOCK_FARMACIA = ("jefe_farmacia", "superusuario")
# Lectura del catálogo de inventario: la necesitan también los médicos y
# enfermeros para registrar los medicamentos/insumos aplicados en la consulta.
ROLES_INVENTARIO_LECTURA = (*ROLES_FARMACIA, "medico", "enfermero")


def _formato_fecha(valor) -> Optional[str]:
    """ISO corto (YYYY-MM-DD HH:MM) para los timestamps de entrega."""
    return str(valor)[:16] if valor else None


def _solo_digitos(valor) -> str:
    """Normaliza cédulas: 'V-18234567' y '18234567' comparan igual."""
    return re.sub(r"\D", "", str(valor or ""))


def _nombres_personal(ids: List[Optional[int]]) -> Dict[int, str]:
    """Mapa id → nombre del personal (para el registro de quién entregó)."""
    limpios = [i for i in ids if i]
    if not limpios:
        return {}
    try:
        filas = (
            supabase.table("personal")
            .select("id, nombre")
            .in_("id", limpios)
            .execute()
            .data
            or []
        )
    except Exception:
        return {}
    return {f["id"]: f.get("nombre", "") for f in filas}


def _detalles_receta(receta_id: int) -> List[RecetaDetalleItemSchema]:
    try:
        detalles = (
            supabase.table("receta_detalles")
            .select("medicamento_id, cantidad_prescrita, cantidad_despachada, posologia")
            .eq("receta_id", receta_id)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("consultar los detalles de la receta")
    if not detalles:
        return []
    ids_validos = [d["medicamento_id"] for d in detalles if d.get("medicamento_id")]
    nombres = {}
    if ids_validos:
        try:
            inventario = (
                supabase.table("inventario_medicamentos")
                .select("id, nombre")
                .in_("id", ids_validos)
                .execute()
                .data
                or []
            )
        except Exception:
            db_fail("consultar el inventario de medicamentos")
        nombres = {m["id"]: m.get("nombre", "") for m in inventario}

    return [
        RecetaDetalleItemSchema(
            medicamento_id=d["medicamento_id"],
            nombre_medicamento=(
                nombres.get(d["medicamento_id"], "Desconocido")
                if d.get("medicamento_id")
                else "Sin registro en inventario"
            ),
            cantidad_prescrita=d.get("cantidad_prescrita", 0),
            cantidad_despachada=d.get("cantidad_despachada", 0),
            posologia=d.get("posologia", ""),
        )
        for d in detalles
    ]


def _a_receta(
    fila: dict, nombres_personal: Optional[Dict[int, str]] = None
) -> RecetaResponseSchema:
    entregada_por_id = fila.get("entregada_por_id")
    entregada_por = None
    if entregada_por_id:
        entregada_por = (
            (nombres_personal or {}).get(entregada_por_id)
            if nombres_personal is not None
            else _nombres_personal([entregada_por_id]).get(entregada_por_id)
        )
    return RecetaResponseSchema(
        id=fila["id"],
        codigo_receta=fila.get("codigo_receta", ""),
        paciente_cedula=fila.get("paciente_cedula", ""),
        paciente_nombre=fila.get("paciente_nombre", ""),
        medico=fila.get("medico", ""),
        estado=fila.get("estado", "PENDIENTE"),
        fecha_emision=_formato_fecha(
            fila.get("fecha_emision") or fila.get("created_at")
        ),
        entregada_por_id=entregada_por_id,
        entregada_por=entregada_por,
        entregada_at=_formato_fecha(fila.get("entregada_at")),
        recibida_at=_formato_fecha(fila.get("recibida_at")),
        recibida_paciente_id=fila.get("recibida_paciente_id"),
        detalles=_detalles_receta(fila["id"]),
    )


@router.get("/recetas/pendientes", response_model=List[RecetaResponseSchema])
def listar_recetas_pendientes(
    limite: int = Query(default=20, ge=1, le=50),
    centro_id: Optional[int] = None,
    _: Dict[str, Any] = Depends(exigir_roles(*ROLES_FARMACIA)),
) -> List[RecetaResponseSchema]:
    """Recetas emitidas por los médicos pendientes de despacho en la farmacia."""
    try:
        query = (
            supabase.table("recetas")
            .select("*")
            .eq("estado", "PENDIENTE")
            .order("id", desc=True)
            .limit(limite)
        )
        if centro_id:
            query = query.eq("clinica_id", centro_id)
        filas = query.execute().data or []
    except Exception:
        db_fail("consultar las recetas pendientes")

    return [_a_receta(f) for f in filas]


@router.get("/recetas/paciente/{cedula}", response_model=List[RecetaResponseSchema])
def listar_recetas_paciente(
    cedula: str,
    usuario: Dict[str, Any] = Depends(exigir_paciente_o_staff),
) -> List[RecetaResponseSchema]:
    """Recetas del paciente con su estado de despacho/entrega (portal del paciente)."""
    try:
        filas = (
            supabase.table("recetas")
            .select("*")
            .ilike("paciente_cedula", f"%{_solo_digitos(cedula)}")
            .order("id", desc=True)
            .limit(30)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("consultar las recetas del paciente")

    nombres = _nombres_personal([f.get("entregada_por_id") for f in filas])
    return [_a_receta(f, nombres) for f in filas]


@router.get("/recetas/{codigo_o_cedula}", response_model=RecetaResponseSchema)
def buscar_receta(
    codigo_o_cedula: str,
    _: Dict[str, Any] = Depends(exigir_roles(*ROLES_FARMACIA)),
) -> RecetaResponseSchema:
    """Busca una receta por código (RX-2026-XXXX) o por cédula del paciente."""
    texto = codigo_o_cedula.strip().replace("#", "").upper()
    if not texto:
        not_found("Receta")

    try:
        if texto.startswith("RX-"):
            filas = (
                supabase.table("recetas")
                .select("*")
                .eq("codigo_receta", texto)
                .execute()
                .data
            )
        else:
            filas = (
                supabase.table("recetas")
                .select("*")
                .ilike("paciente_cedula", f"%{texto}")
                .order("id", desc=True)
                .limit(5)
                .execute()
                .data
            )
    except Exception:
        db_fail("buscar la receta")

    if not filas:
        not_found("Receta")

    fila = filas[0]
    return _a_receta(fila)


@router.post("/recetas/{receta_id}/entregar", status_code=status.HTTP_200_OK)
def entregar_receta(
    receta_id: int,
    payload: RecetaEntregarRequestSchema,
    usuario: Dict[str, Any] = Depends(exigir_roles(*ROLES_FARMACIA)),
) -> dict:
    """El farmacéutico entrega los medicamentos y registra la cédula de quien recibe
    (primera confirmación de la entrega)."""
    try:
        filas = (
            supabase.table("recetas")
            .select("id, estado, codigo_receta, paciente_cedula, paciente_nombre")
            .eq("id", receta_id)
            .execute()
            .data
        )
    except Exception:
        db_fail("validar la receta")
    if not filas:
        not_found("Receta")

    estado = filas[0].get("estado", "PENDIENTE")
    if estado not in ("PENDIENTE", "DESPACHADA"):
        fail(
            f"La receta está en estado {estado} y ya no puede entregarse.",
            status.HTTP_409_CONFLICT,
        )

    try:
        supabase.table("recetas").update(
            {
                "estado": "ENTREGADA",
                "entregada_por_id": usuario.get("personal_id"),
                "entregada_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", receta_id).execute()
    except Exception:
        db_fail("registrar la entrega")

    # Fase 5: aviso automático al paciente ("tu receta está lista").
    # Un fallo del correo nunca debe interrumpir la entrega.
    try:
        notificar_receta_entregada(filas[0])
    except Exception:
        pass

    registrar_accion(
        usuario,
        "entrega_receta",
        "recetas",
        receta_id,
        detalle=f"Recibida por cédula {payload.cedula_paciente}",
    )
    return {
        "status": "success",
        "message": "Entrega registrada. El paciente debe confirmar la recepción en su portal.",
        "receta_id": receta_id,
    }


@router.post("/recetas/{receta_id}/recibir", status_code=status.HTTP_200_OK)
def recibir_receta(
    receta_id: int,
    usuario: Dict[str, Any] = Depends(exigir_paciente),
) -> dict:
    """El paciente confirma en su portal que recibió los medicamentos
    (segunda confirmación: cierra el ciclo de la entrega)."""
    try:
        filas = (
            supabase.table("recetas")
            .select("id, estado, paciente_cedula")
            .eq("id", receta_id)
            .execute()
            .data
        )
    except Exception:
        db_fail("validar la receta")
    if not filas:
        not_found("Receta")

    fila = filas[0]
    if _solo_digitos(fila.get("paciente_cedula")) != _solo_digitos(
        usuario.get("cedula")
    ):
        fail("Solo puede confirmar sus propias recetas.", status.HTTP_403_FORBIDDEN)

    estado = fila.get("estado", "PENDIENTE")
    if estado != "ENTREGADA":
        fail(
            f"La receta está en estado {estado}. Espere a que la farmacia la entregue.",
            status.HTTP_409_CONFLICT,
        )

    try:
        supabase.table("recetas").update(
            {
                "estado": "RECIBIDA",
                "recibida_at": datetime.now(timezone.utc).isoformat(),
                "recibida_paciente_id": usuario.get("paciente_id"),
            }
        ).eq("id", receta_id).execute()
    except Exception:
        db_fail("registrar la recepción")

    registrar_accion(
        usuario,
        "recepcion_receta",
        "recetas",
        receta_id,
        detalle="Confirmación del paciente en su portal",
    )
    return {
        "status": "success",
        "message": "Recepcion confirmada. Su receta queda cerrada en la farmacia.",
        "receta_id": receta_id,
    }


@router.get("/inventario", response_model=List[InventarioItemSchema])
def listar_inventario(
    q: str = Query(default="", description="Filtra por nombre del medicamento"),
    solo_alertas: bool = Query(default=False, description="Solo medicamentos bajo o sin stock"),
    _: Dict[str, Any] = Depends(exigir_roles(*ROLES_INVENTARIO_LECTURA)),
) -> List[InventarioItemSchema]:
    """Inventario de la farmacia para verificar disponibilidad de lo recetado."""
    try:
        query = supabase.table("inventario_medicamentos").select("*").eq("activo", True)
        if q:
            query = query.ilike("nombre", f"%{q}%")
        filas = query.order("nombre").execute().data or []
    except Exception:
        db_fail("consultar el inventario")

    resultado: List[InventarioItemSchema] = []
    for m in filas:
        stock = m.get("stock_actual") or 0
        minimo = m.get("stock_minimo")
        if solo_alertas and (minimo is None or stock > minimo):
            continue
        resultado.append(
            InventarioItemSchema(
                id=m["id"],
                nombre=m.get("nombre", ""),
                presentacion=m.get("presentacion"),
                concentracion=m.get("concentracion"),
                stock_actual=stock,
                stock_minimo=minimo,
                unidad=m.get("unidad", "unidad"),
                categoria=m.get("categoria"),
                vencimiento=m.get("vencimiento"),
            )
        )
    return resultado


@router.post("/despachar", status_code=status.HTTP_200_OK)
def despachar_receta(
    payload: DespacharRecetaRequestSchema,
    usuario: Dict[str, Any] = Depends(exigir_roles(*ROLES_FARMACIA)),
) -> dict:
    """Despacha una receta: valida existencias, descuenta inventario y actualiza estados."""
    try:
        receta = (
            supabase.table("recetas")
            .select("id, estado")
            .eq("id", payload.receta_id)
            .execute()
            .data
        )
    except Exception:
        db_fail("validar la receta")
    if not receta:
        not_found("Receta")
    if receta[0].get("estado", "PENDIENTE").upper() == "DESPACHADA":
        fail("La receta ya fue despachada.", status.HTTP_409_CONFLICT)

    detalles = {
        d["medicamento_id"]: d
        for d in (
            supabase.table("receta_detalles")
            .select("medicamento_id, cantidad_prescrita, cantidad_despachada, id")
            .eq("receta_id", payload.receta_id)
            .execute()
            .data
            or []
        )
    }

    # 1. Validar cantidades contra la receta
    for item in payload.items:
        detalle = detalles.get(item.medicamento_id)
        if not detalle:
            fail(f"El medicamento {item.medicamento_id} no pertenece a esta receta.")
        restante = detalle.get("cantidad_prescrita", 0) - detalle.get(
            "cantidad_despachada", 0
        )
        if item.cantidad_despachada > restante:
            fail(
                f"Cantidad a despachar excede lo prescrito para el medicamento {item.medicamento_id}."
            )

    # 2. Validar existencias en inventario
    ids = [i.medicamento_id for i in payload.items]
    try:
        inventario = {
            m["id"]: m
            for m in (
                supabase.table("inventario_medicamentos")
                .select("id, nombre, stock_actual")
                .in_("id", ids)
                .execute()
                .data
                or []
            )
        }
    except Exception:
        db_fail("consultar el inventario")
    for item in payload.items:
        med = inventario.get(item.medicamento_id)
        if not med:
            fail(f"Medicamento {item.medicamento_id} no existe en el inventario.")
        if (med.get("stock_actual") or 0) < item.cantidad_despachada:
            fail(
                f"Stock insuficiente de {med.get('nombre', '')}: disponible {med.get('stock_actual', 0)}.",
                status.HTTP_409_CONFLICT,
            )

    # 3. Aplicar despacho
    try:
        for item in payload.items:
            detalle = detalles[item.medicamento_id]
            supabase.table("inventario_medicamentos").update(
                {"stock_actual": (inventario[item.medicamento_id].get("stock_actual") or 0) - item.cantidad_despachada}
            ).eq("id", item.medicamento_id).execute()
            supabase.table("receta_detalles").update(
                {"cantidad_despachada": detalle.get("cantidad_despachada", 0) + item.cantidad_despachada}
            ).eq("id", detalle["id"]).execute()
        supabase.table("recetas").update({"estado": "DESPACHADA"}).eq(
            "id", payload.receta_id
        ).execute()
    except Exception:
        db_fail("procesar el despacho")

    total_despachado = sum(i.cantidad_despachada for i in payload.items)
    registrar_accion(
        usuario,
        "despacho_receta",
        "recetas",
        payload.receta_id,
        detalle=f"{total_despachado} unidad(es) despachadas",
    )
    return {
        "status": "success",
        "message": "Despacho procesado e inventario actualizado con éxito",
        "receta_id": payload.receta_id,
        "medicamentos_despachados": total_despachado,
    }

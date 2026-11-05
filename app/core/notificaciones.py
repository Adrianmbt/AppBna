"""Notificaciones al paciente (Fase 5): envío por correo + auditoría en BD.

Toda notificación queda registrada en la tabla `notificaciones` para que el
paciente vea el historial en su portal y el admin pueda auditar los envíos.
Si SMTP no está configurado, el correo se omite pero el registro se guarda
con estado 'demo'.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.core.database import supabase
from app.core.mail import (
    enviar_recordatorio_cita,
    enviar_receta_entregada,
    enviar_resultados_disponibles,
    smtp_habilitado,
)

TIPO_RECETA_ENTREGADA = "receta_entregada"
TIPO_RECORDATORIO_CITA = "recordatorio_cita"
TIPO_AVISO_PERSONAL = "aviso_personal"
TIPO_RESULTADOS_DISPONIBLES = "resultados_disponibles"


def _solo_digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def ya_notificada(tipo: str, referencia: str) -> bool:
    """Evita correos duplicados para el mismo evento (cita/receta)."""
    try:
        filas = (
            supabase.table("notificaciones")
            .select("id")
            .eq("tipo", tipo)
            .eq("referencia", referencia)
            .limit(1)
            .execute()
            .data
            or []
        )
        return bool(filas)
    except Exception:
        return False


def registrar(
    paciente_id: Optional[str],
    tipo: str,
    asunto: str,
    destinatario: str = "",
    enviado: bool = False,
    detalle: str = "",
    referencia: str = "",
    estado_forzado: Optional[str] = None,
    canal: str = "correo",
) -> bool:
    """Guarda la notificación en la bitácora. Nunca interrumpe el flujo principal."""
    if estado_forzado:
        estado = estado_forzado
    elif not smtp_habilitado():
        estado = "demo"
        detalle = detalle or "SMTP no configurado (modo demo)"
    elif enviado:
        estado = "enviado"
    else:
        estado = "error"
    fila = {
        "paciente_id": paciente_id,
        "tipo": tipo,
        "canal": canal,
        "asunto": asunto[:200],
        "destinatario": destinatario or None,
        "estado": estado,
        "detalle": detalle or None,
        "referencia": referencia or None,
        "enviado_en": _ahora(),
    }
    try:
        supabase.table("notificaciones").insert(fila).execute()
        return True
    except Exception:
        return False


def _pacientes_por_id(ids: List[Any]) -> Dict[str, dict]:
    limpios = [str(i) for i in ids if i]
    if not limpios:
        return {}
    try:
        filas = (
            supabase.table("historias_clinicas")
            .select("id, cedula, nombre_completo, email, telefono")
            .in_("id", limpios)
            .execute()
            .data
            or []
        )
        return {str(f["id"]): f for f in filas}
    except Exception:
        return {}


def notificar_receta_entregada(receta: Dict[str, Any]) -> bool:
    """Aviso al paciente cuando la farmacia entrega su receta (evento automático).

    `receta` debe traer id, codigo_receta, paciente_cedula y paciente_nombre.
    """
    referencia = f"receta:{receta.get('id')}"
    if ya_notificada(TIPO_RECETA_ENTREGADA, referencia):
        return True

    codigo = receta.get("codigo_receta") or ""
    digitos = _solo_digitos(receta.get("paciente_cedula"))
    try:
        pacientes = (
            supabase.table("historias_clinicas")
            .select("id, nombre_completo, email")
            .ilike("cedula", f"%{digitos}")
            .limit(1)
            .execute()
            .data
            or []
        ) if digitos else []
    except Exception:
        return False
    if not pacientes:
        return False

    paciente = pacientes[0]
    email = (paciente.get("email") or "").strip()
    nombre = paciente.get("nombre_completo") or receta.get("paciente_nombre") or "paciente"
    asunto = f"Receta {codigo} entregada — confirma en tu portal"
    if not email:
        registrar(
            paciente["id"],
            TIPO_RECETA_ENTREGADA,
            asunto,
            detalle="El paciente no tiene correo registrado",
            referencia=referencia,
            estado_forzado="omitido",
        )
        return False

    enviado = enviar_receta_entregada(nombre.split(" ")[0], codigo, email)
    registrar(
        paciente["id"],
        TIPO_RECETA_ENTREGADA,
        asunto,
        destinatario=email,
        enviado=enviado,
        detalle="" if enviado else "Fallo SMTP al enviar",
        referencia=referencia,
    )
    return enviado


def notificar_resultados_disponibles(orden: Dict[str, Any]) -> bool:
    """Aviso al paciente cuando su orden de estudios tiene resultados (Fase 6)."""
    referencia = f"orden:{orden.get('id')}"
    if ya_notificada(TIPO_RESULTADOS_DISPONIBLES, referencia):
        return True

    comprobante = orden.get("comprobante_orden") or ""
    estudios = orden.get("estudios") or []
    try:
        pacientes = (
            supabase.table("historias_clinicas")
            .select("id, nombre_completo, email")
            .eq("id", orden.get("paciente_id"))
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:
        return False
    if not pacientes:
        return False

    paciente = pacientes[0]
    email = (paciente.get("email") or "").strip()
    nombre = (paciente.get("nombre_completo") or "paciente").split(" ")[0]
    asunto = "Resultados de estudios disponibles — BNA Salud"
    if not email:
        registrar(
            paciente["id"],
            TIPO_RESULTADOS_DISPONIBLES,
            asunto,
            detalle="El paciente no tiene correo registrado",
            referencia=referencia,
            estado_forzado="omitido",
        )
        return False

    enviado = enviar_resultados_disponibles(nombre, comprobante, len(estudios), email)
    registrar(
        paciente["id"],
        TIPO_RESULTADOS_DISPONIBLES,
        asunto,
        destinatario=email,
        enviado=enviado,
        detalle="" if enviado else "Fallo SMTP al enviar",
        referencia=referencia,
    )
    return enviado


def procesar_recordatorios(horas_antes: int = 24) -> int:
    """Envía recordatorios de citas dentro de las próximas `horas_antes` horas.

    Lo invoca el programador cada hora; es idempotente gracias a la columna
    `referencia` (una sola notificación por cita).
    """
    ahora = datetime.now()
    limite = ahora + timedelta(hours=horas_antes)
    try:
        citas = (
            supabase.table("citas")
            .select(
                "id, fecha_cita, hora_inicio, centro_salud, especialidad, "
                "estado, paciente_id"
            )
            .gte("fecha_cita", ahora.date().isoformat())
            .lte("fecha_cita", (ahora.date() + timedelta(days=horas_antes // 24 + 1)).isoformat())
            .not_.in_("estado", ["cancelada", "completada", "finalizada"])
            .execute()
            .data
            or []
        )
    except Exception:
        return 0

    candidatas = []
    for cita in citas:
        try:
            momento = datetime.fromisoformat(
                f"{str(cita['fecha_cita'])[:10]}T{str(cita['hora_inicio'])[:5]}:00"
            )
        except Exception:
            continue
        if ahora < momento <= limite:
            candidatas.append(cita)
    if not candidatas:
        return 0

    pacientes = _pacientes_por_id([c.get("paciente_id") for c in candidatas])
    enviadas = 0
    for cita in candidatas:
        paciente = pacientes.get(str(cita.get("paciente_id"))) or {}
        nombre = paciente.get("nombre_completo") or "paciente"
        fecha_larga = momentolargo(cita)
        hora = str(cita["hora_inicio"])[:5]
        asunto = "Recordatorio de tu cita médica — BNA Salud"

        # Canal correo (comportamiento original)
        email = (paciente.get("email") or "").strip()
        referencia = f"cita:{cita['id']}"
        if not email:
            registrar(
                cita.get("paciente_id"),
                TIPO_RECORDATORIO_CITA,
                asunto,
                detalle="El paciente no tiene correo registrado",
                referencia=referencia,
                estado_forzado="omitido",
            )
        elif not ya_notificada(TIPO_RECORDATORIO_CITA, referencia):
            enviado = enviar_recordatorio_cita(
                nombre.split(" ")[0],
                fecha_larga,
                hora,
                cita.get("centro_salud") or "",
                cita.get("especialidad") or "",
                email,
            )
            registrar(
                cita.get("paciente_id"),
                TIPO_RECORDATORIO_CITA,
                asunto,
                destinatario=email,
                enviado=enviado,
                detalle=f"Cita {cita['id']} del {cita['fecha_cita']} {hora}",
                referencia=referencia,
            )
            enviadas += 1 if enviado else 0
    return enviadas


def momentolargo(cita: Dict[str, Any]) -> str:
    """Fecha larga en español para la plantilla del recordatorio."""
    DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    MESES = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    try:
        d = datetime.strptime(str(cita["fecha_cita"])[:10], "%Y-%m-%d")
        return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}"
    except Exception:
        return str(cita.get("fecha_cita") or "")

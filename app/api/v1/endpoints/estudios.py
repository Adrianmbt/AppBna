import json
import secrets
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.deps import exigir_roles, exigir_staff, usuario_actual
from app.core.config import settings
from app.api.v1.errors import db_fail, fail, not_found
from app.api.v1.utils import parse_json_list
from app.core.bitacora import registrar_accion
from app.core.database import supabase
from app.core.notificaciones import notificar_resultados_disponibles
from app.schemas.schemas import (
    EstudioProcesadoResponse,
    OrdenEstudiosCreate,
    OrdenEstudiosResponse,
    OrdenResultadosUpdate,
    ParametroResultado,
    ProcesarEstudioRequest,
)

router = APIRouter(tags=["Estudios / OCR"])

MODELO_VISION = "gemini-1.5-flash"

PROMPTS: Dict[str, str] = {
    "laboratorio": (
        "Eres un transcriptor de resultados de laboratorio. Lee la imagen adjunta y "
        "extrae los parámetros de laboratorio. Responde SOLO con JSON válido con esta "
        "forma exacta (sin texto adicional, sin markdown): "
        '{"nombre":"<nombre del examen, ej. Hemograma completo>",'
        '"parametros":[{"parametro":"<nombre>","valor":"<valor>","unidad":"<unidad si aparece, ej. g/dL o mg/dL>","rango":"<rango de referencia si aparece>"}]}'
        " Si un dato no está en la imagen, usa cadena vacía. No inventes valores."
    ),
    "imagen": (
        "Eres un radiólogo. Analiza la imagen adjunta (radiografía, tomografía, "
        "resonancia o ecografía). Responde SOLO con JSON válido con esta forma exacta "
        "(sin texto adicional, sin markdown): "
        '{"nombre":"<tipo de estudio, ej. Radiografía de tórax>",'
        '"descripcion":"<descripción de los hallazgos visibles>",'
        '"conclusion":"<impresión diagnóstica o conclusión del estudio>"}'
        " Si no puedes interpretar la imagen, usa descripcion y conclusion vacías."
    ),
    "funcional": (
        "Eres un especialista en estudios funcionales (electrocardiograma, espirometría, "
        "etc.). Analiza la imagen adjunta. Responde SOLO con JSON válido con esta forma "
        "exacta (sin texto adicional, sin markdown): "
        '{"nombre":"<tipo de estudio, ej. Electrocardiograma de reposo>",'
        '"parametros":[{"parametro":"<nombre>","valor":"<valor>","unidad":"<unidad si aparece>","rango":"<rango de referencia si aparece>"}],'
        '"conclusion":"<interpretación o conclusión del estudio>"}'
        " Si un dato no está en la imagen, usa cadena vacía. No inventes valores."
    ),
}


def _limpiar_base64(data: str) -> str:
    """Acepta data-URL (data:image/png;base64,...) o base64 puro."""
    if data.startswith("data:"):
        if "," in data:
            data = data.split(",", 1)[1]
    return data


def _extraer_json(texto: str) -> dict:
    """Extrae el primer objeto JSON de la respuesta del modelo."""
    texto = texto.strip()
    # Quitar posibles cercos de markdown ```json ... ```
    if texto.startswith("```"):
        lineas = texto.splitlines()
        if lineas:
            lineas = lineas[1:]
        if lineas and lineas[-1].strip().startswith("```"):
            lineas = lineas[:-1]
        texto = "\n".join(lineas).strip()
    inicio = texto.find("{")
    fin = texto.rfind("}")
    if inicio == -1 or fin <= inicio:
        raise HTTPException(502, "El modelo no devolvió JSON válido.")
    try:
        return json.loads(texto[inicio : fin + 1])
    except Exception:
        raise HTTPException(502, "No se pudo interpretar la respuesta del modelo.")


def _gemini_vision(imagen_base64: str, prompt: str) -> Optional[dict]:
    if not settings.GOOGLE_API_KEY:
        return None
    try:
        import requests

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{MODELO_VISION}:generateContent"
        )
        r = requests.post(
            url,
            params={"key": settings.GOOGLE_API_KEY},
            json={
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": _limpiar_base64(imagen_base64),
                            }
                        },
                    ]
                }],
                "generationConfig": {
                    "temperature": 0.1,
                    "response_mime_type": "application/json",
                },
            },
            timeout=45,
        )
        if r.status_code != 200:
            return None
        partes = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
        texto = "".join(p.get("text", "") for p in partes).strip()
        if not texto:
            return None
        return _extraer_json(texto)
    except HTTPException:
        raise
    except Exception:
        return None


def _normalizar(extraido: dict, tipo: str) -> EstudioProcesadoResponse:
    parametros: List[ParametroResultado] = []
    for p in extraido.get("parametros", []) or []:
        if not isinstance(p, dict):
            continue
        parametros.append(
            ParametroResultado(
                parametro=str(p.get("parametro", "") or "").strip(),
                valor=str(p.get("valor", "") or "").strip(),
                unidad=str(p.get("unidad", "") or "").strip() or None,
                rango=str(p.get("rango", "") or "").strip() or None,
            )
        )
    return EstudioProcesadoResponse(
        tipo_estudio=tipo,
        nombre=str(extraido.get("nombre", "") or "").strip(),
        parametros=parametros,
        descripcion=str(extraido.get("descripcion", "") or "").strip() or None,
        conclusion=str(extraido.get("conclusion", "") or "").strip() or None,
    )


@router.post("/procesar", response_model=EstudioProcesadoResponse)
def procesar_estudio(
    payload: ProcesarEstudioRequest,
    _: dict = Depends(exigir_staff),
) -> EstudioProcesadoResponse:
    """Extrae resultados de un estudio (laboratorio, imagen o funcional) desde una foto/escaneo."""
    tipo = payload.tipo_estudio
    if tipo not in PROMPTS:
        raise HTTPException(400, "tipo_estudio debe ser: laboratorio, imagen o funcional.")

    extraido = _gemini_vision(payload.imagen_base64, PROMPTS[tipo])
    if extraido is None:
        raise HTTPException(
            502,
            "No se pudo procesar la imagen (¿GOOGLE_API_KEY configurada? ¿Gemini disponible?).",
        )
    return _normalizar(extraido, tipo)


# ============================================================
# ÓRDENES DE ESTUDIOS
# La orden es una entidad propia de la historia clínica: se emite
# (estado 'solicitada') y luego se completan resultados (estado
# 'con_resultados'), pudiendo ser en una consulta posterior.
# ============================================================

def _generar_comprobante_orden() -> str:
    return f"ORD-{secrets.randbelow(90000) + 10000}"


def _a_orden(fila: dict) -> OrdenEstudiosResponse:
    paciente = fila.get("historias_clinicas") or {}
    return OrdenEstudiosResponse(
        id=fila["id"],
        comprobante_orden=fila.get("comprobante_orden", ""),
        paciente_id=fila.get("paciente_id", ""),
        paciente_cedula=paciente.get("cedula"),
        paciente_nombre=paciente.get("nombre_completo"),
        consulta_id=fila.get("consulta_id"),
        cita_id=fila.get("cita_id"),
        origen=fila.get("origen", "consulta"),
        estado=fila.get("estado", "solicitada"),
        prioridad=fila.get("prioridad", "normal"),
        medico_nombre=fila.get("medico_nombre", ""),
        especialidad=fila.get("especialidad", ""),
        estudios=parse_json_list(fila.get("estudios")),
        created_at=fila.get("created_at"),
        resultados_at=fila.get("resultados_at"),
    )


@router.post("/ordenes", status_code=201, response_model=OrdenEstudiosResponse)
def crear_orden(
    payload: OrdenEstudiosCreate,
    _: dict = Depends(exigir_staff),
) -> OrdenEstudiosResponse:
    """Emite una orden médica de estudios (laboratorio, imagen o funcional)."""
    try:
        paciente = (
            supabase.table("historias_clinicas")
            .select("id")
            .eq("id", payload.paciente_id)
            .execute()
            .data
        )
    except Exception:
        db_fail("validar al paciente")
    if not paciente:
        not_found("Paciente")

    if not payload.estudios:
        fail("La orden debe incluir al menos un estudio.")

    registro = {
        "paciente_id": payload.paciente_id,
        "consulta_id": payload.consulta_id,
        "cita_id": payload.cita_id,
        "origen": payload.origen,
        "estado": "solicitada",
        "prioridad": payload.prioridad,
        "medico_id": payload.medico_id,
        "medico_nombre": payload.medico_nombre or "",
        "especialidad": payload.especialidad or "Medicina General",
        "estudios": [
            {**e.model_dump(), "estado": "solicitado"} for e in payload.estudios
        ],
        "comprobante_orden": _generar_comprobante_orden(),
    }
    try:
        creado = supabase.table("ordenes_estudios").insert(registro).execute()
    except Exception:
        db_fail("emitir la orden de estudios")

    return _a_orden(creado.data[0])


@router.get("/ordenes", response_model=List[OrdenEstudiosResponse])
def listar_ordenes_general(
    estado: Optional[str] = None,
    limite: int = 50,
    _: dict = Depends(exigir_staff),
) -> List[OrdenEstudiosResponse]:
    """Listado general de órdenes de estudios para la unidad de laboratorio.

    Filtrable por estado ('solicitada' | 'con_resultados'); trae los datos
    del paciente para la cola de trabajo del personal.
    """
    try:
        query = (
            supabase.table("ordenes_estudios")
            .select("*, historias_clinicas(id, cedula, nombre_completo)")
            .order("created_at", desc=True)
            .limit(limite)
        )
        if estado:
            query = query.eq("estado", estado)
        filas = query.execute().data or []
    except Exception:
        db_fail("listar las órdenes de estudios")
    return [_a_orden(f) for f in filas]


@router.get("/ordenes/paciente/{paciente_id}", response_model=List[OrdenEstudiosResponse])
def listar_ordenes(
    paciente_id: str,
    usuario: dict = Depends(usuario_actual),
) -> List[OrdenEstudiosResponse]:
    """Lista las órdenes de estudios de un paciente.

    Acceso: el propio paciente o el personal autenticado.
    """
    if usuario.get("tipo") != "staff" and usuario.get("paciente_id") != paciente_id:
        raise HTTPException(
            status_code=403,
            detail="Solo puede consultar sus propias órdenes de estudios.",
        )
    try:
        filas = (
            supabase.table("ordenes_estudios")
            .select("*")
            .eq("paciente_id", paciente_id)
            .order("created_at", desc=True)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("listar las órdenes de estudios")
    return [_a_orden(c) for c in filas]


@router.post("/ordenes/{orden_id}/resultados", response_model=OrdenEstudiosResponse)
def registrar_resultados(
    orden_id: str,
    payload: OrdenResultadosUpdate,
    usuario: dict = Depends(exigir_roles("medico", "enfermero", "superusuario")),
) -> OrdenEstudiosResponse:
    """Registra los resultados de una orden previamente emitida.

    Rol: enfermero (laboratorio), médico o superusuario.
    """
    try:
        filas = (
            supabase.table("ordenes_estudios")
            .select("*")
            .eq("id", orden_id)
            .execute()
            .data
        )
    except Exception:
        db_fail("validar la orden de estudios")
    if not filas:
        not_found("Orden de estudios")

    from datetime import datetime

    estudios = [e.model_dump() for e in payload.estudios]
    if not estudios:
        fail("Debe incluir al menos un estudio con resultado.")

    actualizado = {
        "estudios": estudios,
        "estado": "con_resultados",
        "resultados_at": datetime.now().isoformat(),
    }
    if payload.medico_nombre:
        actualizado["medico_nombre"] = payload.medico_nombre
    if payload.especialidad:
        actualizado["especialidad"] = payload.especialidad

    try:
        supabase.table("ordenes_estudios").update(actualizado).eq("id", orden_id).execute()
    except Exception:
        db_fail("registrar los resultados de la orden")

    try:
        fila = (
            supabase.table("ordenes_estudios")
            .select("*")
            .eq("id", orden_id)
            .execute()
            .data[0]
        )
    except Exception:
        db_fail("recargar la orden actualizada")

    # Fase 6: aviso al paciente cuando los resultados quedan disponibles.
    try:
        notificar_resultados_disponibles(fila)
    except Exception:
        pass

    registrar_accion(usuario, "resultados_orden", "ordenes_estudios", orden_id)

    return _a_orden(fila)

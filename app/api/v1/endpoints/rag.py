from typing import Dict, List

from fastapi import APIRouter

from app.core.config import settings
from app.schemas.schemas import RAGQuery, RAGResponse

router = APIRouter(tags=["RAG / Asistente"])

FALLBACKS: List[Dict[str, str]] = [
    {
        "palabras": ["cita", "agendar", "pedir", "reservar"],
        "respuesta": (
            "Para solicitar una cita en nuestra red municipal haz clic en el botón "
            "\"Pedir Cita\" del centro de salud de tu preferencia (fase piloto: CITAB). "
            "Se abrirá un formulario con tus datos, especialidad y fecha. Recibirás un "
            "código de confirmación. Si tienes dificultades llama al +58 281 000 0001."
        ),
    },
    {
        "palabras": ["centro", "horario", "horarios", "aliado", "red"],
        "respuesta": (
            "La red municipal cuenta con 6 centros: CITAB (Clínica de los Trabajadores, "
            "Lun-Vie 7AM-6PM), Clínica de la Mujer (Lun-Sáb 7AM-5PM), Clínica del Niño "
            "(Lun-Sáb 7AM-6PM), Clínica Municipal José Pérez Fernández (Lun-Vie 7AM-5PM), "
            "Centro Oncológico (Lun-Vie 7AM-5PM) y Jornadas de Salud "
            "Móviles (fines de semana). Todos comparten el mismo historial clínico."
        ),
    },
    {
        "palabras": ["emergencia", "urgente", "urgencia", "triaje", "24"],
        "respuesta": (
            "Si enfrentas una emergencia médica acude de inmediato al centro más cercano. "
            "El CITAB y el Hospital del municipio atienden urgencias 24 horas; un equipo de "
            "triaje evaluará tu caso. Para emergencias graves llama al +58 281 000 0000. "
            "¡Cada minuto cuenta!"
        ),
    },
    {
        "palabras": ["receta", "medicina", "farmacia", "medicamento"],
        "respuesta": (
            "Para el despacho de recetas, el módulo de Farmacia busca la receta por su "
            "código (RX-2026-XXXX) o por la cédula del paciente, valida el stock y actualiza "
            "el inventario automáticamente al despachar."
        ),
    },
    {
        "palabras": ["historia", "historial", "consulta", "expediente", "paciente"],
        "respuesta": (
            "Cada paciente de la red tiene una historia clínica única por su cédula. "
            "Puedes consultar el historial completo (consultas, diagnóstico CIE-10, "
            "tratamientos y laboratorios) en el Portal del Paciente."
        ),
    },
    {
        "palabras": ["personal", "turno", "médico", "doctor", "guardia"],
        "respuesta": (
            "La disponibilidad de personal por centro de salud está disponible en el módulo "
            "de Talento Humano, con los turnos y el personal en guardia de cada clínica."
        ),
    },
]

RESPUESTA_DEFAULT = (
    "Gracias por tu consulta. Un agente del Instituto de Salud Municipal te contactará a la "
    "brevedad para brindarte la información que necesitas."
)


def _respuesta_fallback(pregunta: str) -> str:
    texto = pregunta.lower()
    for regla in FALLBACKS:
        if any(p in texto for p in regla["palabras"]):
            return regla["respuesta"]
    return RESPUESTA_DEFAULT


def _gemini(pregunta: str) -> str | None:
    """Intenta responder con Google Gemini; retorna None si no está disponible."""
    if not settings.GOOGLE_API_KEY:
        return None
    try:
        import requests

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-1.5-flash:generateContent"
        )
        r = requests.post(
            url,
            params={"key": settings.GOOGLE_API_KEY},
            json={
                "contents": [{
                    "parts": [{
                        "text": (
                            "Eres el asistente del Instituto de Salud del Municipio Simón "
                            "Bolívar (Barcelona, Venezuela). Responde de forma breve y útil "
                            f"a: {pregunta}"
                        )
                    }]
                }]
            },
            timeout=10,
        )
        if r.status_code != 200:
            return None
        partes = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
        if partes:
            return partes[0].get("text", "").strip() or None
    except Exception:
        return None
    return None


@router.post("", response_model=RAGResponse)
@router.post("/", response_model=RAGResponse)
def responder(payload: RAGQuery) -> RAGResponse:
    """Responde preguntas del asistente (Gemini con respaldo local)."""
    respuesta = _gemini(payload.pregunta) or _respuesta_fallback(payload.pregunta)
    return RAGResponse(
        respuesta=respuesta,
        fuentes=[{
            "tipo": "modelo_local",
            "confianza": "media" if not settings.GOOGLE_API_KEY else "alta",
        }],
    )

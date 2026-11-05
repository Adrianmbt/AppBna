import unicodedata
from typing import List

from fastapi import APIRouter, HTTPException

from app.schemas.schemas import CentroSaludResponse
from app.core.database import supabase

router = APIRouter(tags=["Centros de Salud"])

# Catálogo de presentación por código de clínica (desde el boceto)
CATALOGO = {
    "CLN-CITAB": {
        "subtitulo": "Clínica de los Trabajadores",
        "tipo": "Aliado",
        "horario": "Lun - Vie 7:00 AM - 6:00 PM",
        "servicios": [
            "Medicina Interna", "Medicina General", "Traumatología",
            "Ginecología (citologías)", "Nefrología", "Cardiología",
            "Emergencia 24 horas", "Terapia de la Conducta",
            "Cirugía de Mano", "Cirugía General", "Fisiatría",
            "Pediatría", "Endocrinología", "Gastroenterología",
            "Epidemiología", "Fisioterapia", "Oftalmología",
            "Ecografía", "Laboratorio Clínico",
        ],
        "logo": "/identidad visual/Citab.jpeg",
        "fondoColor": "#1d52d8",
        "textColor": "secondary",
        "tagText": "text-secondary",
        "bgTag": "bg-secondary/10",
    },
    "CLN-MUJER": {
        "subtitulo": "Atención integral de la mujer",
        "tipo": "Especializada",
        "horario": "Lun - Sáb 7:00 AM - 5:00 PM",
        "servicios": [
            "Traumatología", "Medicina Familiar", "Medicina Interna",
            "Medicina General", "Ginecología (citologías y biopsias)",
            "Alergología", "Cardiología", "Radioterapia Oncológica",
            "Psiquiatría", "Pediatría", "Mamografía", "Ecografía",
            "Odontología", "Unidad de Patología Cervico-Uterina",
            "Parto Humanizado", "Inmunizaciones",
            "Laboratorio de Anatomía Patológica", "Laboratorio Clínico",
        ],
        "logo": "/identidad visual/CliMujer.jpeg",
        "fondoColor": "#541e8c",
        "textColor": "rose-700",
        "tagText": "text-rose-700",
        "bgTag": "bg-rose-50",
    },
    "CLN-NINO": {
        "subtitulo": "Pediatría y crecimiento infantil",
        "tipo": "Especializada",
        "horario": "Lun - Sáb 7:00 AM - 6:00 PM",
        "servicios": [
            "Nefrología", "Terapia de la Conducta", "Inmunología",
            "Neumología", "Psicología", "Epidemiología",
            "Psicopedagogía", "Terapia Educativa", "Cirugía Pediátrica",
            "Consulta de Niño Sano", "Consulta por Emergencias",
            "Odontología", "Inmunizaciones",
        ],
        "logo": "/identidad visual/CliNiño.jpeg",
        "fondoColor": "#00b4d8",
        "textColor": "cyan-700",
        "tagText": "text-cyan-700",
        "bgTag": "bg-cyan-50",
    },
    "CLN-ONCO": {
        "subtitulo": "Oncología y cuidados paliativos",
        "tipo": "Especializado",
        "horario": "Lun - Vie 7:00 AM - 5:00 PM",
        "servicios": ["Oncología", "Quimioterapia", "Cuidados Paliativos"],
        "logo": "/identidad visual/Oncologico.jpeg",
        "fondoColor": "#6f42c1",
        "textColor": "purple-700",
        "tagText": "text-purple-700",
        "bgTag": "bg-purple-50",
    },
    "CLN-JORNADAS": {
        "subtitulo": "Atención comunitaria itinerante",
        "tipo": "Comunitario",
        "horario": "Fines de semana · Calendario público",
        "servicios": ["Atención Primaria", "Vacunación", "Despistaje"],
        "logo": "/identidad visual/JornadasSaludBna.jpeg",
        "fondoColor": "#0d9488",
        "textColor": "emerald-700",
        "tagText": "text-emerald-700",
        "bgTag": "bg-emerald-50",
    },
    "CLN-MUNICIPAL": {
        "subtitulo": "Atención médica municipal",
        "tipo": "Municipal",
        "horario": "Lun - Vie 7:00 AM - 5:00 PM",
        "servicios": [
            "Control de Niño Sano", "Medicina Interna", "Medicina General",
            "Pediatría", "Ginecología (citologías y biopsias)",
            "Ecografía", "Parto Humanizado", "Inmunizaciones",
        ],
        "logo": "/identidad visual/ClinicaMunicipalJosePerezFernandez.jpeg",
        "fondoColor": "#059669",
        "textColor": "emerald-700",
        "tagText": "text-emerald-700",
        "bgTag": "bg-emerald-50",
    },
}

# Datos de respaldo (si Supabase no responde) para no romper la página
MAQUETA_FALLBACK: List[dict] = [
    {
        "id": 1, "nombre": "Clínica del Niño", "codigo": "CLN-NINO", "parroquia": "El Carmen",
        "direccion": "Barcelona, Anzoátegui", "activo": True,
    },
    {
        "id": 2, "nombre": "Clínica de los Trabajadores (CITAB)", "codigo": "CLN-CITAB", "parroquia": "El Carmen",
        "direccion": "Barcelona, Anzoátegui", "activo": True,
    },
    {
        "id": 3, "nombre": "Clínica de la Mujer", "codigo": "CLN-MUJER", "parroquia": "San Cristóbal",
        "direccion": "Barcelona, Anzoátegui", "activo": True,
    },
    {
        "id": 4, "nombre": "Centro Oncológico Municipal", "codigo": "CLN-ONCO", "parroquia": "El Carmen",
        "direccion": "Barcelona, Anzoátegui", "activo": True,
    },
    {
        "id": 5, "nombre": "Jornadas de Salud Móviles", "codigo": "CLN-JORNADAS", "parroquia": "General",
        "direccion": "Atención Itinerante - Municipio Simón Bolívar", "activo": True,
    },
    {
        "id": 6, "nombre": "Clínica Municipal José Pérez Fernández", "codigo": "CLN-MUNICIPAL", "parroquia": "El Carmen",
        "direccion": "Barcelona, Anzoátegui", "activo": True,
    },
]


def _normalizar(texto: str) -> str:
    """Minúsculas sin tildes, para comparar especialidades y nombres de centro."""
    descompuesto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in descompuesto if not unicodedata.combining(c)).strip().lower()


# Algunas filas de `clinicas` pueden llegar sin código; se resuelve por nombre.
_CODIGO_POR_NOMBRE = {_normalizar(f["nombre"]): f["codigo"] for f in MAQUETA_FALLBACK}


def _extras_de(fila: dict) -> dict:
    """Catálogo de presentación del centro, por código o, si falta, por nombre."""
    codigo = fila.get("codigo") or _CODIGO_POR_NOMBRE.get(
        _normalizar(fila.get("nombre", "")), ""
    )
    return CATALOGO.get(codigo, {})


def _combinar_especialidades(*listas) -> List[str]:
    """Une listas de especialidades sin duplicar por tildes ni mayúsculas."""
    vistos: set[str] = set()
    salida: List[str] = []
    for lista in listas:
        for nombre in lista or []:
            limpio = (nombre or "").strip()
            clave = _normalizar(limpio)
            if clave and clave not in vistos:
                vistos.add(clave)
                salida.append(limpio)
    return salida


def _especialidades_reales() -> dict[int, List[str]]:
    """Especialidades con personal asignado, agrupadas por centro de salud.

    Es una sola consulta: el portal público la usa para completar el catálogo
    con lo que realmente atiende cada sede (el catálogo es solo presentación).
    """
    try:
        personal = (
            supabase.table("personal")
            .select("clinica_id, especialidad")
            .execute()
            .data
            or []
        )
    except Exception:
        return {}
    agrupadas: dict[int, List[str]] = {}
    for fila in personal:
        centro_id = fila.get("clinica_id")
        nombre = (fila.get("especialidad") or "").strip()
        if centro_id is None or not nombre:
            continue
        agrupadas.setdefault(int(centro_id), []).append(nombre)
    return agrupadas


def _aplicar_catalogo(fila: dict, reales: List[str] | None = None) -> CentroSaludResponse:
    """Combina la fila de la tabla clinicas con el catálogo visual por código."""
    extras = _extras_de(fila)
    base = {
        "id": fila.get("id"),
        "codigo": fila.get("codigo", ""),
        "nombre": fila.get("nombre", ""),
        "subtitulo": extras.get("subtitulo", fila.get("nombre", "")),
        "tipo": extras.get("tipo", "Aliado"),
        "parroquia": fila.get("parroquia", ""),
        "direccion": fila.get("direccion", ""),
        "horario": extras.get("horario", "Consultar horario"),
        # Catálogo primero (orden y redacción curada) + lo que hay en personal.
        "servicios": _combinar_especialidades(extras.get("servicios", []), reales),
        "logo": extras.get("logo", "/identidad visual/SBna.jpeg"),
        "fondoColor": extras.get("fondoColor", "#00677d"),
        "disabled": not fila.get("activo", True),
    }
    extras_fields = {"textColor", "tagText", "bgTag"}
    for campo in extras_fields:
        if campo in extras:
            base[campo] = extras[campo]
    return CentroSaludResponse(**base)


@router.get("", response_model=List[CentroSaludResponse])
@router.get("/", response_model=List[CentroSaludResponse])
def listar_centros() -> List[CentroSaludResponse]:
    """Lista los centros de salud de la red municipal (desde Supabase)."""
    try:
        res = supabase.table("clinicas").select("*").order("id").execute()
        filas = res.data or []
    except Exception:
        return [_aplicar_catalogo(f) for f in MAQUETA_FALLBACK]
    reales = _especialidades_reales()
    return [
        _aplicar_catalogo(f, reales.get(int(f.get("id") or 0), [])) for f in filas
    ]


@router.get("/{centro_id}", response_model=CentroSaludResponse)
def obtener_centro(centro_id: int) -> CentroSaludResponse:
    """Obtiene el detalle de un centro de salud por su ID."""
    try:
        res = supabase.table("clinicas").select("*").eq("id", centro_id).execute()
        if res.data:
            reales = _especialidades_reales().get(int(centro_id), [])
            return _aplicar_catalogo(res.data[0], reales)
    except Exception:
        pass
    for f in MAQUETA_FALLBACK:
        if f["id"] == centro_id:
            return _aplicar_catalogo(f)
    raise HTTPException(status_code=404, detail="Centro de salud no encontrado.")
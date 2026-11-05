"""Panel institucional: resumen global por centro de salud.

Lo consumen las cuentas globales del portal público (`admin_sistemas` y
`director`). Todos los datos salen de Supabase, la misma base que usa el
portal, y se agregan en el backend para que el panel funcione desde
cualquier lugar sin depender del sistema interno local.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List
from unicodedata import normalize
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from app.api.v1.deps import exigir_rol_global
from app.api.v1.errors import db_fail
from app.core.database import supabase

router = APIRouter(tags=["Panel Institucional"])

TZ = ZoneInfo("America/Caracas")
TAM_LOTE = 1000
MAX_FILAS = 100_000  # tope de seguridad para no paginar sin fin
STOCK_BAJO = 10


def _sin_tildes(valor: Any) -> str:
    texto = str(valor or "").strip().lower()
    return normalize("NFD", texto).encode("ascii", "ignore").decode("utf-8")


def _traer(tabla: str, columnas: str) -> List[Dict[str, Any]]:
    """Lee una tabla completa, paginando por lotes de 1000 filas."""
    if supabase is None:
        db_fail("consultar el panel")
    filas: List[Dict[str, Any]] = []
    desde = 0
    while desde < MAX_FILAS:
        try:
            lote = (
                supabase.table(tabla)
                .select(columnas)
                .order("id")
                .range(desde, desde + TAM_LOTE - 1)
                .execute()
                .data
                or []
            )
        except Exception:
            db_fail(f"consultar {tabla}")
        filas.extend(lote)
        if len(lote) < TAM_LOTE:
            break
        desde += TAM_LOTE
    return filas


def _contar_por(filas: Iterable[Dict[str, Any]], clave: str) -> Dict[Any, int]:
    conteo: Dict[Any, int] = {}
    for fila in filas:
        valor = fila.get(clave)
        conteo[valor] = conteo.get(valor, 0) + 1
    return conteo


@router.get("/resumen")
def resumen_panel(_: Dict[str, Any] = Depends(exigir_rol_global)) -> Dict[str, Any]:
    """Resumen completo (totales y por centro) para el panel institucional."""
    clinicas = _traer("clinicas", "id, nombre, codigo, parroquia, activo")
    personal = _traer("personal", "id, clinica_id, cargo, especialidad, estado")
    historias = _traer("historias_clinicas", "id")
    citas = _traer("citas", "id, paciente_id, centro_id, estado, especialidad, fecha_cita")
    consultas = _traer("consultas", "id, paciente_id, cita_id, medico_id, especialidad")
    recetas = _traer("recetas", "id, clinica_id, estado")
    stock = _traer("stock_clinica", "id, clinica_id, medicamento_id, cantidad_actual")
    usuarios = _traer("usuarios", "id, rol, activo")

    hoy = datetime.now(TZ).date().isoformat()

    # Centro de cada consulta: por su cita o, si no tiene, por el médico.
    clinica_de_cita = {c.get("id"): c.get("centro_id") for c in citas}
    clinica_de_medico = {p.get("id"): p.get("clinica_id") for p in personal}

    consultas_por_centro: Dict[Any, int] = {}
    pacientes_consulta: Dict[Any, set] = {}
    for consulta in consultas:
        centro = clinica_de_cita.get(consulta.get("cita_id"))
        if centro is None:
            centro = clinica_de_medico.get(consulta.get("medico_id"))
        consultas_por_centro[centro] = consultas_por_centro.get(centro, 0) + 1
        paciente = consulta.get("paciente_id")
        if paciente:
            pacientes_consulta.setdefault(centro, set()).add(paciente)

    citas_por_centro = _contar_por(citas, "centro_id")
    pacientes_cita: Dict[Any, set] = {}
    for cita in citas:
        paciente = cita.get("paciente_id")
        if paciente:
            pacientes_cita.setdefault(cita.get("centro_id"), set()).add(paciente)

    personal_por_centro = _contar_por(personal, "clinica_id")
    medicos_por_centro: Dict[Any, int] = {}
    for persona in personal:
        if "medic" in _sin_tildes(persona.get("cargo")) or persona.get("especialidad"):
            centro = persona.get("clinica_id")
            medicos_por_centro[centro] = medicos_por_centro.get(centro, 0) + 1

    recetas_por_centro = _contar_por(recetas, "clinica_id")

    stock_unidades: Dict[Any, int] = {}
    stock_agotados: Dict[Any, int] = {}
    stock_bajos: Dict[Any, int] = {}
    for item in stock:
        centro = item.get("clinica_id")
        cantidad = item.get("cantidad_actual") or 0
        stock_unidades[centro] = stock_unidades.get(centro, 0) + cantidad
        if cantidad <= 0:
            stock_agotados[centro] = stock_agotados.get(centro, 0) + 1
        elif cantidad <= STOCK_BAJO:
            stock_bajos[centro] = stock_bajos.get(centro, 0) + 1

    def centro_resumen(clinica: Dict[str, Any]) -> Dict[str, Any]:
        centro = clinica.get("id")
        citas_centro = [c for c in citas if c.get("centro_id") == centro]
        estados: Dict[str, int] = {}
        for cita in citas_centro:
            estado = _sin_tildes(cita.get("estado")) or "sin_estado"
            estados[estado] = estados.get(estado, 0) + 1
        pendientes = sum(
            total for estado, total in estados.items() if estado in ("pendiente", "confirmada")
        )
        personal_centro = personal_por_centro.get(centro, 0)
        activos = sum(
            1
            for p in personal
            if p.get("clinica_id") == centro
            and _sin_tildes(p.get("estado")) in ("activo", "", "true")
        )
        pacientes = pacientes_cita.get(centro, set()) | pacientes_consulta.get(centro, set())
        recetas_centro = [r for r in recetas if r.get("clinica_id") == centro]
        recetas_pendientes = sum(
            1 for r in recetas_centro if _sin_tildes(r.get("estado")) == "pendiente"
        )
        return {
            "id": centro,
            "nombre": clinica.get("nombre") or f"Centro {centro}",
            "codigo": clinica.get("codigo"),
            "parroquia": clinica.get("parroquia"),
            "activo": clinica.get("activo", True),
            "citas": len(citas_centro),
            "citas_hoy": sum(1 for c in citas_centro if c.get("fecha_cita") == hoy),
            "citas_pendientes": pendientes,
            "citas_canceladas": estados.get("cancelada", 0),
            "consultas": consultas_por_centro.get(centro, 0),
            "pacientes": len(pacientes),
            "personal": personal_centro,
            "personal_activos": activos,
            "medicos": medicos_por_centro.get(centro, 0),
            "recetas": len(recetas_centro),
            "recetas_pendientes": recetas_pendientes,
            "stock_unidades": stock_unidades.get(centro, 0),
            "stock_agotados": stock_agotados.get(centro, 0),
            "stock_bajos": stock_bajos.get(centro, 0),
            "citas_por_estado": [
                {"estado": estado, "total": total}
                for estado, total in sorted(estados.items(), key=lambda kv: -kv[1])
            ],
        }

    por_centro = [centro_resumen(c) for c in clinicas]

    estados_global = _contar_por(citas, "estado")
    especialidades = _contar_por(citas, "especialidad")
    cargos = _contar_por(personal, "cargo")
    roles = _contar_por(usuarios, "rol")

    def _top(conteo: Dict[Any, int], limite: int = 8) -> List[Dict[str, Any]]:
        return [
            {"nombre": str(nombre or "Sin dato"), "total": total}
            for nombre, total in sorted(conteo.items(), key=lambda kv: -kv[1])[:limite]
        ]

    usuarios_por_rol = []
    for rol, total in sorted(roles.items(), key=lambda kv: -kv[1]):
        activos = sum(
            1
            for u in usuarios
            if u.get("rol") == rol and u.get("activo", True)
        )
        usuarios_por_rol.append(
            {"rol": str(rol or "sin_rol"), "total": total, "activos": activos}
        )

    total_stock = sum(stock_unidades.values())
    total_agotados = sum(stock_agotados.values())
    total_bajos = sum(stock_bajos.values())

    return {
        "generado_en": datetime.now(TZ).isoformat(timespec="seconds"),
        "zona_horaria": "America/Caracas",
        "hoy": hoy,
        "totales": {
            "centros": len(clinicas),
            "centros_activos": sum(1 for c in clinicas if c.get("activo", True)),
            "citas": len(citas),
            "citas_hoy": sum(1 for c in citas if c.get("fecha_cita") == hoy),
            "citas_pendientes": sum(
                total
                for estado, total in estados_global.items()
                if _sin_tildes(estado) in ("pendiente", "confirmada")
            ),
            "consultas": len(consultas),
            "pacientes": len(historias),
            "personal": len(personal),
            "personal_activos": sum(
                1 for p in personal if _sin_tildes(p.get("estado")) in ("activo", "", "true")
            ),
            "medicos": sum(medicos_por_centro.values()),
            "recetas": len(recetas),
            "recetas_pendientes": sum(
                1 for r in recetas if _sin_tildes(r.get("estado")) == "pendiente"
            ),
            "stock_unidades": total_stock,
            "stock_agotados": total_agotados,
            "stock_bajos": total_bajos,
        },
        "por_centro": por_centro,
        "citas_por_estado": [
            {"estado": str(estado or "sin_estado"), "total": total}
            for estado, total in sorted(estados_global.items(), key=lambda kv: -kv[1])
        ],
        "especialidades": _top(especialidades),
        "personal_por_cargo": _top(cargos),
        "usuarios_por_rol": usuarios_por_rol,
    }

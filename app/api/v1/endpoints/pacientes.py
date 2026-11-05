from datetime import datetime
import html
import re
import secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, status

from app.api.v1.deps import exigir_paciente_o_staff, exigir_roles
from app.api.v1.errors import db_fail, fail, not_found
from app.api.v1.utils import parse_json_list, parse_list
from app.core.bitacora import registrar_accion
from app.core.database import supabase
from app.core.mail import enviar_aviso_personal, smtp_habilitado
from app.core.notificaciones import registrar as registrar_notificacion
from app.core.security import crear_token, hash_secreto
from app.schemas.schemas import (
    ConsultaDetalleResponse,
    HistoriaClinicaResponse,
    HistoriaClinicaUpdate,
    InsumoAplicado,
    LaboratorioResultado,
    MedicamentoItem,
    MedicoPacienteResponse,
    NotificacionItem,
    NotificarPacienteRequest,
    PacienteLoginResponse,
    PacienteRegistroRequest,
    ProgresoPacienteResponse,
)

router = APIRouter(tags=["Pacientes"])


def _a_historia(fila: dict) -> HistoriaClinicaResponse:
    return HistoriaClinicaResponse(
        id=fila["id"],
        numero_historia=fila.get("numero_historia", ""),
        tipo_cedula=fila.get("tipo_cedula", "V"),
        cedula=fila.get("cedula", ""),
        nombre_completo=fila.get("nombre_completo", ""),
        fecha_nacimiento=fila.get("fecha_nacimiento"),
        telefono=fila.get("telefono"),
        email=fila.get("email"),
        tipo_sangre=fila.get("tipo_sangre"),
        antecedentes_medicos=parse_list(fila.get("antecedentes_medicos")),
        alergias=parse_list(fila.get("alergias")),
        created_at=fila.get("created_at"),
    )


def _nombres_personal(medico_ids: List[int]) -> Dict[int, str]:
    """Mapa medico_id -> nombre completo para una lista de ids."""
    ids = [i for i in medico_ids if i]
    if not ids:
        return {}
    try:
        filas = (
            supabase.table("personal")
            .select("id, nombre, apellido")
            .in_("id", ids)
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


def _buscar_paciente(cedula: str) -> dict:
    limpia = re.sub(r"\D", "", cedula.strip())
    try:
        filas = (
            supabase.table("historias_clinicas")
            .select("*")
            .eq("cedula", limpia)
            .limit(1)
            .execute()
            .data
        )
    except Exception:
        db_fail("buscar al paciente")
    if not filas:
        not_found("Paciente")
    return filas[0]


@router.get("/empleado/{cedula}")
def buscar_empleado(cedula: str) -> Dict[str, Any]:
    """Datos de un trabajador de la Alcaldía para autollenar el registro.

    Busca en `personal` por cédula (solo dígitos). Es público porque el
    formulario de registro lo consulta antes de crear la cuenta; devuelve
    únicamente los datos de contacto necesarios para el autollenado.
    """
    digitos = re.sub(r"\D", "", cedula or "")
    if not digitos:
        fail("La cédula debe contener al menos un dígito.")

    try:
        filas = (
            supabase.table("personal")
            .select("id, cedula, nombre, apellido, telefono, email, cargo, especialidad, clinica_id")
            .eq("cedula", digitos)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("buscar al trabajador")

    if not filas:
        return {"encontrado": False}

    fila = filas[0]
    return {
        "encontrado": True,
        "nombre": fila.get("nombre") or "",
        "apellido": fila.get("apellido") or "",
        "nombre_completo": f"{fila.get('nombre') or ''} {fila.get('apellido') or ''}".strip(),
        "telefono": fila.get("telefono") or "",
        "email": fila.get("email") or "",
        "cargo": fila.get("cargo") or "",
        "especialidad": fila.get("especialidad") or "",
        "clinica_id": fila.get("clinica_id"),
    }


@router.post(
    "/registrar",
    response_model=PacienteLoginResponse,
    status_code=status.HTTP_201_CREATED,
)
def registrar_paciente(payload: PacienteRegistroRequest) -> PacienteLoginResponse:
    """Auto-registro de un paciente nuevo desde el portal público.

    Crea la historia clínica (`historias_clinicas`) y la cuenta de acceso
    (`usuarios` con rol 'paciente'), y devuelve un token para que el
    paciente quede autenticado de inmediato.
    """
    cedula = re.sub(r"\D", "", payload.cedula.strip())
    if not cedula:
        fail("La cédula debe contener al menos un dígito.")

    try:
        existente = (
            supabase.table("historias_clinicas")
            .select("id, cedula")
            .eq("cedula", cedula)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("verificar la cédula")

    if existente:
        fail(
            "Ya existe un paciente registrado con esta cédula. "
            "Inicie sesión con su cédula y contraseña.",
            status.HTTP_409_CONFLICT,
        )

    # La contraseña del paciente se guarda en `pin_hash` (bcrypt), la columna
    # histórica del esquema; el nombre se conserva para no migrar la BD.
    secreto = payload.password.strip()
    if not (6 <= len(secreto) <= 64):
        fail("La contraseña debe tener entre 6 y 64 caracteres.")

    registro = {
        "tipo_cedula": payload.tipo_cedula.value,
        "cedula": cedula,
        "nombre_completo": payload.nombre_completo.strip(),
        "fecha_nacimiento": payload.fecha_nacimiento.isoformat()
        if payload.fecha_nacimiento
        else None,
        "telefono": payload.telefono,
        "email": str(payload.email) if payload.email else None,
        "tipo_sangre": payload.tipo_sangre,
        "antecedentes_medicos": payload.antecedentes_medicos,
        "alergias": payload.alergias,
        "numero_historia": f"HIS-{payload.tipo_cedula.value}{cedula}",
        "pin_hash": hash_secreto(secreto),
    }
    try:
        creado = supabase.table("historias_clinicas").insert(registro).execute()
        fila = creado.data[0]
    except Exception:
        db_fail("registrar al paciente")

    # Cuenta de acceso del paciente (mismo identificador que el portal).
    # Es complementaria: el login real usa cédula + contraseña contra
    # historias_clinicas, así que un fallo aquí no debe impedir el registro.
    try:
        supabase.table("usuarios").insert(
            {
                "username": f"pac_{cedula}",
                "password_hash": hash_secreto(secrets.token_hex(16)),
                "rol": "paciente",
                "paciente_id": fila["id"],
                "activo": True,
            }
        ).execute()
    except Exception:
        pass

    token = crear_token(
        {
            "tipo": "paciente",
            "rol": "paciente",
            "username": "",
            "personal_id": None,
            "paciente_id": fila["id"],
            "cedula": cedula,
        }
    )
    registrar_accion(
        {"rol": "paciente", "username": cedula, "personal_id": None},
        "registro_paciente",
        "historias_clinicas",
        fila["id"],
    )
    return PacienteLoginResponse(token=token, paciente=_a_historia(fila))


def _a_consulta_detalle(fila: dict) -> ConsultaDetalleResponse:
    return ConsultaDetalleResponse(
        consulta_id=fila["id"],
        fecha=fila.get("created_at") or fila.get("fecha_consulta") or datetime.now(),
        especialidad=fila.get("especialidad", ""),
        medico_nombre=fila.get("medico_nombre", ""),
        cie10_codigo=fila.get("cie10_codigo", ""),
        cie10_descripcion=fila.get("cie10_descripcion", ""),
        motivo_consulta=fila.get("motivo_consulta", ""),
        examen_fisico=fila.get("examen_fisico"),
        tratamiento=fila.get("tratamiento", ""),
        recomendaciones=fila.get("recomendaciones"),
        recetas=[MedicamentoItem(**m) for m in parse_json_list(fila.get("recetas"))],
        laboratorios=[LaboratorioResultado(**l) for l in parse_json_list(fila.get("laboratorios"))],
        estudios=parse_json_list(fila.get("estudios")),
        insumos=[InsumoAplicado(**i) for i in parse_json_list(fila.get("insumos"))],
        ordenes_ids=[str(o) for o in (fila.get("ordenes_ids") or [])],
        comprobante_ref=fila.get("comprobante_ref", ""),
    )


@router.get("/{cedula}", response_model=HistoriaClinicaResponse)
def obtener_paciente(
    cedula: str,
    _: dict = Depends(exigir_paciente_o_staff),
) -> HistoriaClinicaResponse:
    """Obtiene la historia clínica de un paciente por su cédula.

    Acceso: el propio paciente (cédula+contraseña) o el personal autenticado.
    """
    return _a_historia(_buscar_paciente(cedula.strip()))


@router.patch("/{cedula}", response_model=HistoriaClinicaResponse)
def actualizar_paciente(
    cedula: str,
    payload: HistoriaClinicaUpdate,
    _: dict = Depends(exigir_paciente_o_staff),
) -> HistoriaClinicaResponse:
    """Actualiza el perfil editable del paciente (datos clínicos y contacto).

    El paciente puede registrar su tipo de sangre, alergias, antecedentes
    y datos de contacto; el médico los ve en su módulo de consultas.
    """
    fila = _buscar_paciente(cedula.strip())
    datos = payload.model_dump(exclude_unset=True, mode="json")
    if not datos:
        fail("No hay campos para actualizar.")

    # Normalizar listas vacías a [] (evita enviar None que Supabase rechaza).
    for campo in ("alergias", "antecedentes_medicos"):
        if campo in datos and datos[campo] is None:
            datos[campo] = []

    try:
        supabase.table("historias_clinicas").update(datos).eq("id", fila["id"]).execute()
    except Exception:
        db_fail("actualizar los datos del paciente")

    try:
        actualizado = (
            supabase.table("historias_clinicas")
            .select("*")
            .eq("id", fila["id"])
            .execute()
            .data[0]
        )
    except Exception:
        db_fail("recargar los datos actualizados")
    return _a_historia(actualizado)


@router.get("/{cedula}/medico", response_model=MedicoPacienteResponse)
def medico_tratante(
    cedula: str,
    _: dict = Depends(exigir_paciente_o_staff),
) -> MedicoPacienteResponse:
    """Médico principal asignado al paciente (relación médico_pacientes).

    Si aún no hay vínculo formal, se deduce del médico de la última consulta.
    """
    fila = _buscar_paciente(cedula.strip())
    try:
        relacion = (
            supabase.table("medico_pacientes")
            .select("tipo, estado, personal(id, nombre, apellido, especialidad, cargo)")
            .eq("paciente_id", fila["id"])
            .eq("tipo", "principal")
            .eq("estado", "activo")
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:
        relacion = []
    if relacion:
        m = relacion[0].get("personal") or {}
        nombre = f"{m.get('nombre', '')} {m.get('apellido', '')}".strip()
        return MedicoPacienteResponse(
            medico_id=m.get("id"),
            nombre=nombre or None,
            especialidad=m.get("especialidad"),
            tipo=relacion[0].get("tipo", "principal"),
            estado=relacion[0].get("estado", "activo"),
        )

    # Si aún no hay vínculo formal, se deduce del médico elegido en la cita
    # más reciente. Se ignoran las solicitudes del portal que todavía no
    # tienen médico ni fecha asignados por recepción.
    try:
        citas = (
            supabase.table("citas")
            .select("medico_id")
            .eq("paciente_id", fila["id"])
            .not_.eq("estado", "cancelada")
            .order("created_at", desc=True)
            .limit(20)
            .execute()
            .data
            or []
        )
    except Exception:
        citas = []
    cita = next((c for c in citas if c.get("medico_id")), None)
    if cita:
        try:
            medico_cita = (
                supabase.table("personal")
                .select("id, nombre, apellido, especialidad")
                .eq("id", cita["medico_id"])
                .limit(1)
                .execute()
                .data
                or []
            )
        except Exception:
            medico_cita = []
        if medico_cita:
            p = medico_cita[0]
            nombre_cita = f"{p.get('nombre', '')} {p.get('apellido', '')}".strip()
            return MedicoPacienteResponse(
                medico_id=p.get("id"),
                nombre=nombre_cita or None,
                especialidad=p.get("especialidad"),
                tipo="cita",
                estado="activo",
            )

    try:
        consulta = (
            supabase.table("consultas")
            .select("medico_id, medico_nombre, especialidad")
            .eq("paciente_id", fila["id"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:
        consulta = []
    if consulta:
        c = consulta[0]
        return MedicoPacienteResponse(
            medico_id=c.get("medico_id"),
            nombre=c.get("medico_nombre") or None,
            especialidad=c.get("especialidad"),
            tipo="seguimiento",
            estado="activo",
        )
    return MedicoPacienteResponse()


@router.get("/{cedula}/notificaciones", response_model=List[NotificacionItem])
def listar_notificaciones(
    cedula: str,
    _: dict = Depends(exigir_paciente_o_staff),
) -> List[NotificacionItem]:
    """Historial de notificaciones enviadas al paciente (portal del paciente)."""
    fila = _buscar_paciente(cedula.strip())
    try:
        filas = (
            supabase.table("notificaciones")
            .select("*")
            .eq("paciente_id", fila["id"])
            .order("creado_en", desc=True)
            .limit(50)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("consultar las notificaciones")
    return [
        NotificacionItem(
            id=n["id"],
            tipo=n.get("tipo", ""),
            canal=n.get("canal", "correo"),
            asunto=n.get("asunto", ""),
            destinatario=n.get("destinatario"),
            estado=n.get("estado", "pendiente"),
            detalle=n.get("detalle"),
            referencia=n.get("referencia"),
            enviado_en=str(n.get("enviado_en"))[:16] if n.get("enviado_en") else None,
            creado_en=str(n.get("creado_en"))[:16] if n.get("creado_en") else None,
        )
        for n in filas
    ]


@router.post("/{cedula}/notificar", status_code=status.HTTP_200_OK)
def notificar_paciente(
    cedula: str,
    payload: NotificarPacienteRequest,
    usuario: Dict[str, Any] = Depends(exigir_roles("superusuario")),
) -> dict:
    """Envía un aviso por correo al paciente y lo registra en su historial.

    Uso manual del personal (rol superusuario); los avisos automáticos
    (receta entregada, recordatorio de cita) se disparan por evento.
    """
    fila = _buscar_paciente(cedula.strip())
    email = (fila.get("email") or "").strip()
    nombre = (fila.get("nombre_completo") or "").strip()
    if not email:
        fail("El paciente no tiene un correo registrado.", status.HTTP_409_CONFLICT)

    cuerpo_html = html.escape(payload.mensaje).replace("\n", "<br>")
    enviado = enviar_aviso_personal(nombre.split(" ")[0], payload.asunto, cuerpo_html, email)
    registrar_notificacion(
        fila["id"],
        "aviso_personal",
        payload.asunto,
        destinatario=email,
        enviado=enviado,
        detalle=f"Enviado por {usuario.get('username') or 'staff'}",
    )

    from app.core.bitacora import registrar_accion

    registrar_accion(
        usuario,
        "notificacion_manual",
        "historias_clinicas",
        fila["id"],
        detalle=f"Aviso a {email}",
    )
    return {
        "status": "success",
        "message": (
            "Correo enviado al paciente."
            if enviado
            else "Notificación registrada en modo demo (SMTP no configurado)."
            if not smtp_habilitado()
            else "No se pudo enviar el correo; quedó registrado con estado 'error'."
        ),
        "correo_enviado": enviado,
        "paciente_id": str(fila["id"]),
    }


@router.get("/{cedula}/historial", response_model=ProgresoPacienteResponse)
def historial_paciente(
    cedula: str,
    _: dict = Depends(exigir_paciente_o_staff),
) -> ProgresoPacienteResponse:
    """Historial clínico completo del paciente (datos + consultas)."""
    fila = _buscar_paciente(cedula.strip())
    try:
        consultas = (
            supabase.table("consultas")
            .select("*")
            .eq("paciente_id", fila["id"])
            .order("created_at", desc=True)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("cargar el historial clínico")

    nombres = _nombres_personal([c.get("medico_id") for c in consultas])
    historial: List[ConsultaDetalleResponse] = []
    for c in consultas:
        c = dict(c)
        if not c.get("medico_nombre"):
            c["medico_nombre"] = nombres.get(c.get("medico_id"), "")
        historial.append(_a_consulta_detalle(c))

    return ProgresoPacienteResponse(
        paciente=_a_historia(fila),
        total_consultas=len(historial),
        historial=historial,
    )

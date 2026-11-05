import secrets
from datetime import date, time, datetime, timedelta
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import exigir_paciente_o_staff, exigir_staff, exigir_paciente
from app.api.v1.errors import db_fail, fail, not_found
from app.core.bitacora import registrar_accion
from app.core.database import supabase
from app.core.mail import enviar_bienvenida
from app.schemas.schemas import (
    CitaAsignar,
    CitaCancelar,
    CitaConPacienteCreate,
    CitaCreate,
    CitaDetalleResponse,
    CitaEstadoUpdate,
    CitaPosponer,
    CitaResponse,
    CitaSolicitudRequest,
    EstadoCita,
    HistoriaClinicaBase,
)
router = APIRouter(tags=["Citas Médicas"])

# Fase piloto: reservas en línea solo para el CITAB.
CITAB_CENTER_ID = 2

# Ventana horaria por centro (horas) para generar slots de 30 minutos.
HORARIOS_CENTRO: dict[int, tuple[str, str]] = {
    1: ("07:00", "17:00"),  # Clínica del Niño
    2: ("07:00", "22:00"),  # CITAB (incluye turno nocturno de pruebas)
    3: ("07:00", "16:30"),  # Clínica de la Mujer
    4: ("08:00", "16:00"),  # Centro Oncológico
    5: ("08:00", "14:00"),  # Jornadas de Salud
}
PREFIJOS_CONFIRMACION: dict[int, str] = {
    1: "NINO",
    2: "CITAB",
    3: "MUJER",
    4: "ONCO",
    5: "JORNADAS",
}


def _get_db():
    yield None


def _generar_slots(centro_id: int, fecha: date, especialidad_id: Optional[int]) -> List[str]:
    """Slots libres de 30 min para un centro/fecha, excluyendo los ya reservados.

    Las solicitudes del portal (estado 'pendiente') todavía no tienen fecha ni
    hora confirmadas, así que no bloquean cupos. Las citas antiguas que se
    crearon con una fecha provisional tampoco deben reservar el slot.
    """
    try:
        res = (
            supabase.table("citas")
            .select("hora_inicio, estado")
            .eq("centro_id", centro_id)
            .eq("fecha_cita", fecha.isoformat())
            .not_.eq("estado", "cancelada")
            .execute()
        )
    except Exception:
        db_fail("consultar la disponibilidad")
    ocupados = {
        str(r["hora_inicio"])[:5]
        for r in (res.data or [])
        if r.get("hora_inicio") and r.get("estado") != "pendiente"
    }

    apertura, cierre = HORARIOS_CENTRO.get(centro_id, ("08:00", "16:00"))
    inicio = datetime.strptime(apertura, "%H:%M")
    fin = datetime.strptime(cierre, "%H:%M")
    slots: List[str] = []
    while inicio <= fin:
        etiqueta = inicio.strftime("%H:%M")
        if etiqueta not in ocupados:
            slots.append(etiqueta)
        inicio += timedelta(minutes=30)
    return slots


def _upsert_paciente(paciente: HistoriaClinicaBase) -> str:
    """Busca o crea un paciente en historias_clinicas por cédula.

    No crea credenciales: el paciente define su contraseña en el portal con
    «¿Olvidaste tu contraseña?» usando su cédula y su correo. Devuelve el id.
    """
    cedula = paciente.cedula.strip()
    if not cedula.isdigit():
        fail("La cédula debe contener solo dígitos.")
    try:
        existe = (
            supabase.table("historias_clinicas")
            .select("id, cedula, numero_historia")
            .eq("cedula", cedula)
            .execute()
            .data
        )
    except Exception:
        db_fail("verificar el paciente")

    datos = paciente.model_dump(exclude_unset=True, mode="json")
    if existe:
        fila = existe[0]
        actualizables = {
            k: v
            for k, v in datos.items()
            if v is not None and k not in {"cedula", "tipo_cedula"}
        }
        if actualizables:
            try:
                supabase.table("historias_clinicas").update(actualizables).eq(
                    "id", fila["id"]
                ).execute()
            except Exception:
                db_fail("actualizar los datos del paciente")
        return fila["id"]

    registro = dict(datos)
    registro["numero_historia"] = f"HIS-{paciente.tipo_cedula.value}{cedula}"
    try:
        creado = supabase.table("historias_clinicas").insert(registro).execute()
    except Exception:
        db_fail("registrar al paciente")

    email = (registro.get("email") or "").strip()
    if email:
        enviar_bienvenida(
            registro.get("nombre_completo") or f"Paciente {cedula}",
            cedula,
            email,
        )
    return creado.data[0]["id"]


def _generar_codigo(centro_id: int) -> str:
    prefijo = PREFIJOS_CONFIRMACION.get(centro_id, "BNA")
    anio = date.today().year
    for _ in range(5):
        codigo = f"{prefijo}-{anio}-{secrets.token_hex(2).upper()}"
        ocupado = (
            supabase.table("citas")
            .select("id")
            .eq("codigo_confirmacion", codigo)
            .execute()
            .data
        )
        if not ocupado:
            return codigo
    fail("No se pudo generar un código de confirmación único.", status.HTTP_409_CONFLICT)


@router.post("", response_model=CitaResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=CitaResponse, status_code=status.HTTP_201_CREATED)
async def crear_cita(
    payload: Union[CitaConPacienteCreate, CitaCreate],
    db=Depends(_get_db),
) -> CitaResponse:
    """Crea una cita médica (registra al paciente si no existe)."""
    if payload.centro_id != CITAB_CENTER_ID:
        fail(
            "La reserva de citas en línea actualmente solo está disponible para el CITAB durante esta fase.",
            status.HTTP_400_BAD_REQUEST,
        )

    try:
        centro = (
            supabase.table("clinicas")
            .select("id, nombre, activo")
            .eq("id", payload.centro_id)
            .execute()
            .data
        )
    except Exception:
        db_fail("validar el centro de salud")
    if not centro:
        not_found("Centro de salud")
    if not centro[0].get("activo", True):
        fail("Este centro de salud aún no está operativo.", status.HTTP_409_CONFLICT)

    try:
        esp = (
            supabase.table("especialidades")
            .select("id, nombre")
            .eq("id", payload.especialidad_id)
            .execute()
            .data
        )
    except Exception:
        db_fail("validar la especialidad")
    if not esp:
        not_found("Especialidad")

    if payload.fecha_cita < date.today():
        fail("La fecha de la cita no puede estar en el pasado.")

    hora_str = payload.hora_inicio.strftime("%H:%M:%S")
    try:
        ocupada = (
            supabase.table("citas")
            .select("id")
            .eq("centro_id", payload.centro_id)
            .eq("fecha_cita", payload.fecha_cita.isoformat())
            .eq("hora_inicio", hora_str)
            .not_.eq("estado", "cancelada")
            .execute()
            .data
        )
    except Exception:
        db_fail("verificar la disponibilidad del horario")
    if ocupada:
        fail(
            "Ese horario ya fue reservado. Seleccione otro.",
            status.HTTP_409_CONFLICT,
        )

    if isinstance(payload, CitaConPacienteCreate):
        paciente_id = _upsert_paciente(payload.paciente)
    else:
        paciente_id = payload.paciente_id
        try:
            existe_paciente = (
                supabase.table("historias_clinicas")
                .select("id")
                .eq("id", paciente_id)
                .execute()
                .data
            )
        except Exception:
            db_fail("validar al paciente")
        if not existe_paciente:
            not_found("Paciente")

    cita = {
        "paciente_id": paciente_id,
        "centro_id": payload.centro_id,
        "centro_salud": centro[0]["nombre"],
        "especialidad_id": payload.especialidad_id,
        "especialidad": esp[0]["nombre"],
        "fecha_cita": payload.fecha_cita.isoformat(),
        "hora_inicio": hora_str,
        "motivo": payload.motivo,
        "origen": "cita_web",
        "estado": "pendiente",
        "codigo_confirmacion": _generar_codigo(payload.centro_id),
    }
    if payload.medico_id:
        cita["medico_id"] = payload.medico_id
    try:
        creado = supabase.table("citas").insert(cita).execute()
    except Exception:
        db_fail("registrar la cita")

    fila = creado.data[0]

    return CitaResponse(
        id=fila["id"],
        codigo_confirmacion=fila["codigo_confirmacion"],
        paciente_id=paciente_id,
        centro_id=fila["centro_id"],
        especialidad_id=fila["especialidad_id"],
        medico_id=fila.get("medico_id"),
        fecha_cita=fila["fecha_cita"],
        hora_inicio=fila["hora_inicio"],
        motivo=fila.get("motivo"),
        origen=fila.get("origen", "cita_web"),
        estado=fila.get("estado", "pendiente"),
        created_at=fila.get("created_at", datetime.now()),
    )


@router.get("/medicos")
def listar_medicos_por_especialidad(
    centro_id: int,
    especialidad_id: int,
    db=Depends(_get_db),
) -> dict:
    """Devuelve los médicos de una especialidad en un centro, con sus días y horarios."""
    if centro_id != CITAB_CENTER_ID:
        return {"medicos": [], "mensaje": "Centro no disponible para agenda digital."}

    try:
        especialidad = (
            supabase.table("especialidades")
            .select("nombre")
            .eq("id", especialidad_id)
            .limit(1)
            .execute()
            .data
        )
    except Exception:
        db_fail("validar la especialidad")
    if not especialidad:
        not_found("Especialidad")

    nombre_esp = especialidad[0]["nombre"]

    try:
        personal = (
            supabase.table("personal")
            .select("id, nombre, apellido, cedula")
            .eq("clinica_id", centro_id)
            .eq("especialidad", nombre_esp)
            .eq("cargo", "Médico")
            .eq("estado", "ACTIVO")
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("consultar los médicos")

    if not personal:
        return {"medicos": [], "mensaje": "No hay médicos disponibles para esta especialidad."}

    medico_ids = [p["id"] for p in personal]

    try:
        turnos_raw = (
            supabase.table("personal_turnos")
            .select("personal_id, turno_id, observaciones, turnos(nombre, hora_inicio, hora_fin)")
            .in_("personal_id", medico_ids)
            .eq("clinica_id", centro_id)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("consultar los horarios de los médicos")

    turnos_map: dict[int, list] = {}
    for t in turnos_raw:
        pid = t["personal_id"]
        turno_info = t.get("turnos") or {}
        turnos_map.setdefault(pid, []).append({
            "dia": t.get("observaciones", ""),
            "turno_nombre": turno_info.get("nombre", ""),
            "hora_inicio": turno_info.get("hora_inicio", ""),
            "hora_fin": turno_info.get("hora_fin", ""),
        })

    medicos = []
    for p in personal:
        horarios = turnos_map.get(p["id"], [])
        dias_trabajo = sorted({h["dia"] for h in horarios if h["dia"]})
        medicos.append({
            "id": p["id"],
            "nombre_completo": f"Dr(a). {p['nombre']} {p['apellido']}",
            "cedula": p.get("cedula", ""),
            "dias": dias_trabajo,
            "horarios": horarios,
        })

    return {"medicos": medicos}


@router.get("/disponibilidad")
def obtener_disponibilidad(
    centro_id: int,
    especialidad_id: int,
    fecha: date,
    medico_id: Optional[int] = Query(default=None, description="ID del médico para filtrar por su horario"),
    db=Depends(_get_db),
) -> dict:
    """Devuelve los slots libres de 30 minutos para un centro, fecha y (opcionalmente) médico."""
    if centro_id != CITAB_CENTER_ID:
        return {
            "disponible": False,
            "mensaje": "Centro no disponible para agenda digital actualmente.",
            "slots": [],
        }
    try:
        existe = (
            supabase.table("clinicas").select("id").eq("id", centro_id).execute().data
        )
    except Exception:
        db_fail("validar el centro de salud")
    if not existe:
        not_found("Centro de salud")

    if medico_id:
        dia_semana = fecha.strftime("%A")
        dias_es = {
            "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
            "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo",
        }
        dia_es = dias_es.get(dia_semana, "")

        try:
            turnos_medico = (
                supabase.table("personal_turnos")
                .select("turno_id, observaciones, turnos(hora_inicio, hora_fin)")
                .eq("personal_id", medico_id)
                .eq("clinica_id", centro_id)
                .execute()
                .data
                or []
            )
        except Exception:
            db_fail("consultar el horario del médico")

        turno_del_dia = None
        for t in turnos_medico:
            if t.get("observaciones", "").lower() == dia_es.lower():
                turno_del_dia = t
                break

        if not turno_del_dia:
            return {
                "disponible": False,
                "centro_id": centro_id,
                "especialidad_id": especialidad_id,
                "medico_id": medico_id,
                "fecha": fecha.isoformat(),
                "slots": [],
                "mensaje": f"El médico no atiende los {dia_es}.",
            }

        turno_info = turno_del_dia.get("turnos") or {}
        hora_inicio_turno = turno_info.get("hora_inicio", "07:00")[:5]
        hora_fin_turno = turno_info.get("hora_fin", "19:00")[:5]

        slots = _generar_slots(centro_id, fecha, especialidad_id)
        slots_filtrados = [
            s for s in slots
            if hora_inicio_turno <= s < hora_fin_turno
        ]

        return {
            "disponible": bool(slots_filtrados),
            "centro_id": centro_id,
            "especialidad_id": especialidad_id,
            "medico_id": medico_id,
            "fecha": fecha.isoformat(),
            "slots": slots_filtrados,
            "mensaje": "No hay horarios disponibles para esta fecha." if not slots_filtrados else "",
        }

    slots = _generar_slots(centro_id, fecha, especialidad_id)
    return {
        "disponible": bool(slots),
        "centro_id": centro_id,
        "especialidad_id": especialidad_id,
        "fecha": fecha.isoformat(),
        "slots": slots,
        "mensaje": "No hay horarios disponibles para esta fecha." if not slots else "",
    }


def _a_cita_detalle(fila: dict) -> CitaDetalleResponse:
    return CitaDetalleResponse(
        id=fila["id"],
        codigo_confirmacion=fila.get("codigo_confirmacion", ""),
        centro_id=fila.get("centro_id"),
        centro_salud=fila.get("centro_salud", ""),
        especialidad_id=fila.get("especialidad_id"),
        especialidad=fila.get("especialidad", ""),
        medico_id=fila.get("medico_id"),
        medico_nombre=fila.get("medico_nombre", ""),
        fecha_cita=fila.get("fecha_cita"),
        hora_inicio=fila.get("hora_inicio"),
        motivo=fila.get("motivo"),
        estado=fila.get("estado", "pendiente"),
        origen=fila.get("origen", "cita_web"),
        paciente_id=fila.get("paciente_id", ""),
        paciente_nombre=fila.get("paciente_nombre", ""),
        created_at=fila.get("created_at"),
    )


def _nombres_medicos(medico_ids) -> dict:
    """Resuelve {medico_id: 'Dr(a). Nombre Apellido'} para los IDs dados."""
    medico_ids = [m for m in (medico_ids or []) if m]
    if not medico_ids:
        return {}
    try:
        filas = (
            supabase.table("personal")
            .select("id, nombre, apellido")
            .in_("id", medico_ids)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("consultar los médicos asignados")
    return {
        p["id"]: f"Dr(a). {p['nombre']} {p['apellido']}".strip()
        for p in filas
    }


def _anotar_medico(fila: dict) -> None:
    """Agrega fila['medico_nombre'] en sitio a partir de fila['medico_id']."""
    mid = fila.get("medico_id")
    fila["medico_nombre"] = _nombres_medicos([mid]).get(mid, "") if mid else ""


def _nombres_pacientes(paciente_ids) -> dict:
    """Resuelve {paciente_id: nombre_completo} para los IDs dados."""
    ids = [p for p in (paciente_ids or []) if p]
    if not ids:
        return {}
    try:
        filas = (
            supabase.table("historias_clinicas")
            .select("id, nombre_completo")
            .in_("id", ids)
            .execute()
            .data
            or []
        )
    except Exception:
        return {}
    return {p["id"]: p.get("nombre_completo", "") for p in filas}


def _datos_paciente(paciente_id: str) -> dict:
    """Ficha mínima del paciente (nombre y teléfono) para notificaciones."""
    try:
        filas = (
            supabase.table("historias_clinicas")
            .select("id, cedula, nombre_completo, telefono")
            .eq("id", paciente_id)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:
        return {}
    return filas[0] if filas else {}


@router.post(
    "/solicitar",
    response_model=CitaDetalleResponse,
    status_code=status.HTTP_201_CREATED,
)
def solicitar_cita(
    payload: CitaSolicitudRequest,
    usuario: dict = Depends(exigir_paciente),
) -> CitaDetalleResponse:
    """Solicitud de cita del paciente (centro + especialidad).

    No reserva un horario ni elige fecha: crea la cita en estado 'pendiente'
    para que la recepción del centro asigne médico, fecha y hora según la
    disponibilidad real y los turnos de ese centro.
    """
    paciente_id = usuario.get("paciente_id")
    if not paciente_id:
        fail(
            "Su sesión no tiene un paciente asociado. Vuelva a iniciar sesión.",
            status.HTTP_401_UNAUTHORIZED,
        )

    try:
        centro = (
            supabase.table("clinicas")
            .select("id, nombre, activo")
            .eq("id", payload.centro_id)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("validar el centro de salud")
    if not centro:
        not_found("Centro de salud")
    if not centro[0].get("activo", True):
        fail("Este centro de salud aún no está operativo.", status.HTTP_409_CONFLICT)

    try:
        esp = (
            supabase.table("especialidades")
            .select("id, nombre")
            .eq("id", payload.especialidad_id)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("validar la especialidad")
    if not esp:
        not_found("Especialidad")

    # Evita solicitudes duplicadas mientras la anterior siga sin atender.
    try:
        pendientes = (
            supabase.table("citas")
            .select("id")
            .eq("paciente_id", paciente_id)
            .eq("centro_id", payload.centro_id)
            .eq("especialidad_id", payload.especialidad_id)
            .eq("estado", "pendiente")
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("verificar sus solicitudes pendientes")
    if pendientes:
        fail(
            "Ya tiene una solicitud pendiente para esta especialidad en este "
            "centro. Espere la confirmación de recepción.",
            status.HTTP_409_CONFLICT,
        )

    cita = {
        "paciente_id": paciente_id,
        "centro_id": payload.centro_id,
        "centro_salud": centro[0]["nombre"],
        "especialidad_id": payload.especialidad_id,
        "especialidad": esp[0]["nombre"],
        # Sin fecha ni hora: la recepción las asigna al confirmar la solicitud.
        "fecha_cita": None,
        "hora_inicio": None,
        "motivo": payload.motivo,
        "origen": "cita_web",
        "estado": "pendiente",
        "codigo_confirmacion": _generar_codigo(payload.centro_id),
    }
    try:
        creado = supabase.table("citas").insert(cita).execute()
        fila = creado.data[0]
    except Exception:
        db_fail("registrar la solicitud de cita")

    registrar_accion(
        {"rol": "paciente", "username": usuario.get("cedula", ""), "personal_id": None},
        "solicitar_cita",
        "citas",
        fila["id"],
        detalle=(
            f"{centro[0]['nombre']} — {esp[0]['nombre']} — "
            "fecha y hora por asignar en recepción"
        ),
    )

    fila["paciente_nombre"] = _datos_paciente(paciente_id).get("nombre_completo", "")
    return _a_cita_detalle(fila)


@router.get("/mis-citas", response_model=List[CitaDetalleResponse])
def listar_mis_citas(
    usuario: dict = Depends(exigir_paciente),
) -> List[CitaDetalleResponse]:
    """Citas del paciente autenticado (sin necesidad de enviar la cédula)."""
    cedula = (usuario.get("cedula") or "").strip()
    if not cedula:
        fail("Su sesión no tiene una cédula asociada. Vuelva a iniciar sesión.", 401)
    return listar_citas_por_cedula(cedula=cedula, _=usuario)


@router.get("/solicitudes", response_model=List[CitaDetalleResponse])
def listar_solicitudes(
    centro_id: Optional[int] = Query(None, description="Filtrar por centro de salud"),
    _: dict = Depends(exigir_staff),
) -> List[CitaDetalleResponse]:
    """Solicitudes de cita pendientes, para gestión del personal de recepción."""
    try:
        consulta = supabase.table("citas").select("*").eq("estado", "pendiente")
        if centro_id:
            consulta = consulta.eq("centro_id", centro_id)
        filas = consulta.order("created_at", desc=True).limit(100).execute().data or []
    except Exception:
        db_fail("listar las solicitudes de cita")

    nombres_pacientes = _nombres_pacientes([f.get("paciente_id") for f in filas])
    nombres_medicos = _nombres_medicos([f.get("medico_id") for f in filas])
    for f in filas:
        f["paciente_nombre"] = nombres_pacientes.get(f.get("paciente_id"), "")
        f["medico_nombre"] = nombres_medicos.get(f.get("medico_id"), "")
    return [_a_cita_detalle(f) for f in filas]


@router.patch("/{cita_id}/asignar", response_model=CitaDetalleResponse)
async def asignar_cita(
    cita_id: str,
    payload: CitaAsignar,
    usuario: dict = Depends(exigir_staff),
) -> CitaDetalleResponse:
    """Confirma una solicitud asignando médico, fecha y hora.

    La usa el personal de recepción. Actualiza la cita a 'confirmada'.
    """
    try:
        fila = (
            supabase.table("citas")
            .select("*")
            .eq("id", cita_id)
            .limit(1)
            .execute()
            .data
        )
    except Exception:
        db_fail("buscar la cita")
    if not fila:
        not_found("Cita")
    cita_actual = fila[0]

    if cita_actual.get("estado") in {"cancelada", "finalizada"}:
        fail(
            "No se puede asignar una cita cancelada o finalizada.",
            status.HTTP_409_CONFLICT,
        )

    if payload.fecha_cita < date.today():
        fail("La fecha de la cita no puede estar en el pasado.")

    try:
        medico = (
            supabase.table("personal")
            .select("id, nombre, apellido, especialidad, clinica_id, cargo, estado")
            .eq("id", payload.medico_id)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("validar el médico asignado")
    if not medico:
        not_found("Médico")
    medico = medico[0]
    if str(medico.get("estado", "")).upper() != "ACTIVO":
        fail("El médico seleccionado no está activo.", status.HTTP_409_CONFLICT)
    if medico.get("clinica_id") and cita_actual.get("centro_id") and (
        medico["clinica_id"] != cita_actual["centro_id"]
    ):
        fail(
            "El médico no pertenece al centro de salud de la cita.",
            status.HTTP_409_CONFLICT,
        )

    hora_str = payload.hora_inicio.strftime("%H:%M:%S")
    try:
        ocupada = (
            supabase.table("citas")
            .select("id")
            .eq("centro_id", cita_actual["centro_id"])
            .eq("fecha_cita", payload.fecha_cita.isoformat())
            .eq("hora_inicio", hora_str)
            .neq("id", cita_id)
            .not_.eq("estado", "cancelada")
            .execute()
            .data
        )
    except Exception:
        db_fail("verificar la disponibilidad del horario")
    if ocupada:
        fail(
            "Ese horario ya está reservado por otra cita. Seleccione otro.",
            status.HTTP_409_CONFLICT,
        )

    actualizacion = {
        "medico_id": payload.medico_id,
        "fecha_cita": payload.fecha_cita.isoformat(),
        "hora_inicio": hora_str,
        "estado": "confirmada",
    }
    if payload.notas:
        actualizacion["observaciones_medico"] = payload.notas

    try:
        supabase.table("citas").update(actualizacion).eq("id", cita_id).execute()
    except Exception:
        db_fail("asignar la cita")

    registrar_accion(
        usuario,
        "asignar_cita",
        "citas",
        cita_id,
        detalle=(
            f"Médico {payload.medico_id} — "
            f"{payload.fecha_cita.isoformat()} {hora_str[:5]}"
        ),
    )

    paciente = _datos_paciente(cita_actual.get("paciente_id"))

    cita_actual.update(actualizacion)
    cita_actual["paciente_nombre"] = paciente.get("nombre_completo", "")
    _anotar_medico(cita_actual)
    return _a_cita_detalle(cita_actual)


@router.get("/{codigo}", response_model=CitaDetalleResponse)
def buscar_cita(codigo: str) -> CitaDetalleResponse:
    """Busca una cita por su código de confirmación."""
    try:
        fila = (
            supabase.table("citas")
            .select("*, historias_clinicas(nombre_completo)")
            .eq("codigo_confirmacion", codigo.strip().upper())
            .limit(1)
            .execute()
            .data
        )
    except Exception:
        db_fail("buscar la cita")
    if not fila:
        not_found("Cita")
    fila = dict(fila[0])
    relacion = fila.get("historias_clinicas") or {}
    fila["paciente_nombre"] = relacion.get("nombre_completo", "") if relacion else ""
    fila.pop("historias_clinicas", None)
    _anotar_medico(fila)
    return _a_cita_detalle(fila)


@router.get("", response_model=List[CitaDetalleResponse])
@router.get("/", response_model=List[CitaDetalleResponse])
def listar_citas_por_cedula(
    cedula: str = Query(..., description="Cédula del paciente (solo dígitos)"),
    _: dict = Depends(exigir_paciente_o_staff),
) -> List[CitaDetalleResponse]:
    """Lista las citas de un paciente por su cédula."""
    try:
        paciente = (
            supabase.table("historias_clinicas")
            .select("id, nombre_completo")
            .eq("cedula", cedula)
            .limit(1)
            .execute()
            .data
        )
    except Exception:
        db_fail("buscar al paciente")
    if not paciente:
        return []
    try:
        filas = (
            supabase.table("citas")
            .select("*")
            .eq("paciente_id", paciente[0]["id"])
            .order("fecha_cita", desc=True)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("listar las citas")
    nombres_medicos = _nombres_medicos([f.get("medico_id") for f in filas])
    for f in filas:
        f["paciente_nombre"] = paciente[0]["nombre_completo"]
        f["medico_nombre"] = nombres_medicos.get(f.get("medico_id"), "")
    return [_a_cita_detalle(f) for f in filas]


# ---------------------------------------------------------------------------
# TRANSICIONES PERMITIDAS: solo avances lógicos evitan estados incoherentes
# ---------------------------------------------------------------------------
_TRANSICIONES_VALIDAS: dict[str, set[str]] = {
    "pendiente":    {"confirmada", "cancelada"},
    "confirmada":   {"en_espera", "cancelada"},
    "en_espera":    {"en_consulta", "cancelada"},
    "en_consulta":  {"completada", "finalizada", "cancelada"},
    "completada":   {"finalizada"},
    "finalizada":   set(),   # estado terminal
    "cancelada":    set(),   # estado terminal
}


@router.patch("/{cita_id}/estado", response_model=CitaDetalleResponse)
async def actualizar_estado_cita(
    cita_id: str,
    payload: CitaEstadoUpdate,
    usuario: dict = Depends(exigir_staff),
) -> CitaDetalleResponse:
    """Actualiza el estado de una cita médica (uso exclusivo del personal).

    Valida la transición de estado y registra la acción en la bitácora.
    Estados permitidos: pendiente → confirmada → en_espera → en_consulta
                        → completada / finalizada / cancelada.
    """
    # Recuperar la cita actual
    try:
        fila = (
            supabase.table("citas")
            .select("*, historias_clinicas(nombre_completo)")
            .eq("id", cita_id)
            .limit(1)
            .execute()
            .data
        )
    except Exception:
        db_fail("buscar la cita")
    if not fila:
        not_found("Cita")

    cita_actual = fila[0]
    estado_actual = cita_actual.get("estado", "pendiente")
    nuevo_estado = payload.estado.value

    # Validar transición
    permitidos = _TRANSICIONES_VALIDAS.get(estado_actual, set())
    if nuevo_estado not in permitidos:
        fail(
            f"No se puede cambiar el estado '{estado_actual}' a '{nuevo_estado}'. "
            f"Transiciones válidas: {', '.join(permitidos) or 'ninguna (estado terminal)'}.",
            status.HTTP_409_CONFLICT,
        )

    # Construir actualización
    actualizacion: dict = {"estado": nuevo_estado}
    if payload.observaciones:
        actualizacion["observaciones_medico"] = payload.observaciones

    try:
        supabase.table("citas").update(actualizacion).eq("id", cita_id).execute()
    except Exception:
        db_fail("actualizar el estado de la cita")

    # Registrar en bitácora
    registrar_accion(
        usuario,
        "actualizar_estado_cita",
        "citas",
        cita_id,
        detalle=f"Estado: {estado_actual} → {nuevo_estado}",
    )

    # Devolver la cita actualizada con el nombre del paciente
    relacion = cita_actual.get("historias_clinicas") or {}
    cita_actual["paciente_nombre"] = relacion.get("nombre_completo", "") if relacion else ""
    cita_actual.pop("historias_clinicas", None)
    cita_actual["estado"] = nuevo_estado
    if payload.observaciones:
        cita_actual["observaciones_medico"] = payload.observaciones
    _anotar_medico(cita_actual)
    return _a_cita_detalle(cita_actual)


@router.patch("/{cita_id}/posponer", response_model=CitaDetalleResponse)
async def posponer_cita(
    cita_id: str,
    payload: CitaPosponer,
    usuario: dict = Depends(exigir_paciente),
) -> CitaDetalleResponse:
    """Permite al paciente solicitar una postergación de su cita.

    Solo puede posponer citas en estado 'pendiente' o 'confirmada'.
    Valida que el nuevo horario esté libre antes de actualizar.
    """
    # Verificar que la cita existe y pertenece al paciente autenticado
    try:
        fila = (
            supabase.table("citas")
            .select("*, historias_clinicas(nombre_completo, telefono, cedula)")
            .eq("id", cita_id)
            .limit(1)
            .execute()
            .data
        )
    except Exception:
        db_fail("buscar la cita")
    if not fila:
        not_found("Cita")

    cita_actual = fila[0]

    # Solo el propio paciente puede posponer su cita
    if cita_actual.get("paciente_id") != usuario.get("paciente_id"):
        fail("Solo puede modificar sus propias citas.", status.HTTP_403_FORBIDDEN)

    # Solo se pueden posponer citas activas
    estados_posponibles = {"pendiente", "confirmada"}
    if cita_actual.get("estado") not in estados_posponibles:
        fail(
            f"Solo se pueden posponer citas en estado pendiente o confirmada. "
            f"Estado actual: '{cita_actual.get('estado')}'.",
            status.HTTP_409_CONFLICT,
        )

    # Validar que la nueva fecha sea futura
    if payload.nueva_fecha < date.today():
        fail("La nueva fecha no puede estar en el pasado.")

    # Verificar disponibilidad con el MISMO médico asignado a la cita
    nueva_hora_min = payload.nueva_hora.strftime("%H:%M")
    nueva_hora_str = payload.nueva_hora.strftime("%H:%M:%S")
    medico_id = cita_actual.get("medico_id")
    medico_nombre = _nombres_medicos([medico_id]).get(medico_id, "") if medico_id else ""

    if medico_id:
        dia_semana = payload.nueva_fecha.strftime("%A")
        dias_es = {
            "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
            "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo",
        }
        dia_es = dias_es.get(dia_semana, "")
        try:
            turnos_medico = (
                supabase.table("personal_turnos")
                .select("turno_id, observaciones, turnos(hora_inicio, hora_fin)")
                .eq("personal_id", medico_id)
                .eq("clinica_id", cita_actual["centro_id"])
                .execute()
                .data
                or []
            )
        except Exception:
            db_fail("consultar el horario del médico")

        turno_del_dia = next(
            (t for t in turnos_medico if t.get("observaciones", "").lower() == dia_es.lower()),
            None,
        )
        if not turno_del_dia:
            fail(
                f"{medico_nombre or 'El médico asignado'} no atiende los {dia_es}. "
                f"Seleccione otra fecha en la que tenga turno.",
                status.HTTP_409_CONFLICT,
            )

        turno_info = turno_del_dia.get("turnos") or {}
        inicio_turno = turno_info.get("hora_inicio", "07:00")[:5]
        fin_turno = turno_info.get("hora_fin", "19:00")[:5]
        if not (inicio_turno <= nueva_hora_min < fin_turno):
            fail(
                f"{medico_nombre or 'El médico asignado'} solo atiende los {dia_es} de "
                f"{inicio_turno} a {fin_turno}. Seleccione un horario dentro de su turno.",
                status.HTTP_409_CONFLICT,
            )

    # El horario debe estar libre (mismo criterio que la reserva inicial)
    slots_libres = _generar_slots(cita_actual["centro_id"], payload.nueva_fecha, cita_actual.get("especialidad_id"))
    if nueva_hora_min not in slots_libres:
        fail(
            "Ese horario ya fue reservado o no está disponible. Seleccione otro.",
            status.HTTP_409_CONFLICT,
        )

    # Aplicar la postergación
    try:
        supabase.table("citas").update(
            {
                "fecha_cita": payload.nueva_fecha.isoformat(),
                "hora_inicio": nueva_hora_str,
                "estado": "pendiente",   # vuelve a pendiente tras reprogramar
            }
        ).eq("id", cita_id).execute()
    except Exception:
        db_fail("posponer la cita")

    # Registrar en bitácora
    registrar_accion(
        usuario,
        "posponer_cita",
        "citas",
        cita_id,
        detalle=(
            f"Nueva fecha: {payload.nueva_fecha.isoformat()} "
            f"{nueva_hora_str[:5]}"
        ),
    )

    relacion = cita_actual.get("historias_clinicas") or {}

    # Devolver la cita actualizada
    cita_actual.pop("historias_clinicas", None)
    cita_actual["paciente_nombre"] = relacion.get("nombre_completo", "")
    cita_actual["fecha_cita"] = payload.nueva_fecha.isoformat()
    cita_actual["hora_inicio"] = nueva_hora_str
    cita_actual["estado"] = "pendiente"
    _anotar_medico(cita_actual)
    return _a_cita_detalle(cita_actual)


@router.patch("/{cita_id}/cancelar", response_model=CitaDetalleResponse)
async def cancelar_cita(
    cita_id: str,
    payload: CitaCancelar,
    usuario: dict = Depends(exigir_paciente),
) -> CitaDetalleResponse:
    """Permite al paciente cancelar su propia cita.

    Solo se pueden cancelar citas en estado 'pendiente', 'confirmada' o
    'en_espera'. La cancelación es terminal: libera el cupo para otros
    pacientes y registra la acción en la bitácora.
    """
    # Verificar que la cita existe y pertenece al paciente autenticado
    try:
        fila = (
            supabase.table("citas")
            .select("*, historias_clinicas(nombre_completo, telefono)")
            .eq("id", cita_id)
            .limit(1)
            .execute()
            .data
        )
    except Exception:
        db_fail("buscar la cita")
    if not fila:
        not_found("Cita")

    cita_actual = fila[0]

    # Solo el propio paciente puede cancelar su cita
    if cita_actual.get("paciente_id") != usuario.get("paciente_id"):
        fail("Solo puede modificar sus propias citas.", status.HTTP_403_FORBIDDEN)

    # Solo se cancelan citas activas
    estados_cancelables = {"pendiente", "confirmada", "en_espera"}
    if cita_actual.get("estado") not in estados_cancelables:
        fail(
            f"Solo se pueden cancelar citas en estado pendiente, confirmada o "
            f"en espera. Estado actual: '{cita_actual.get('estado')}'.",
            status.HTTP_409_CONFLICT,
        )

    # Aplicar la cancelación
    actualizacion: dict = {"estado": "cancelada"}
    if payload.motivo:
        actualizacion["observaciones_medico"] = payload.motivo

    try:
        supabase.table("citas").update(actualizacion).eq("id", cita_id).execute()
    except Exception:
        db_fail("cancelar la cita")

    # Registrar en bitácora
    registrar_accion(
        usuario,
        "cancelar_cita",
        "citas",
        cita_id,
        detalle=f"Motivo: {payload.motivo or 'No especificado'}",
    )

    relacion = cita_actual.get("historias_clinicas") or {}

    # Devolver la cita actualizada
    cita_actual.pop("historias_clinicas", None)
    cita_actual["paciente_nombre"] = relacion.get("nombre_completo", "")
    cita_actual["estado"] = "cancelada"
    _anotar_medico(cita_actual)
    return _a_cita_detalle(cita_actual)

"""Autenticación de BnaSalud.

Tres vías de acceso:
  • /auth/login        → personal (médicos, farmacia, enfermería): usuario + clave.
  • /auth/institucional → cuentas globales: admin_sistemas y director.
  • /auth/paciente     → portal del paciente: cédula + contraseña.
  • /auth/paciente/recuperar → genera un código de 6 dígitos por correo.
  • /auth/paciente/reset     → restablece la contraseña con ese código.

Los tokens son JWT con expiración (ver app/core/security.py) y las rutas
sensibles de la API los validan mediante app/api/v1/deps.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, status

from app.api.v1.deps import ROLES_GLOBALES
from app.api.v1.errors import db_fail, fail
from app.api.v1.endpoints.pacientes import _a_historia, _buscar_paciente
from app.core.bitacora import registrar_accion
from app.core.config import settings
from app.core.database import supabase
from app.core.mail import enviar_codigo_recuperacion
from app.core.security import (
    crear_token,
    generar_codigo,
    hash_secreto,
    verificar_secreto,
)
from app.schemas.schemas import (
    HistoriaClinicaResponse,
    LoginRequest,
    LoginResponse,
    LoginUsuarioResponse,
    PacienteLoginRequest,
    PacienteLoginResponse,
    RecuperarPasswordRequest,
    RecuperarPasswordResponse,
    ResetPasswordRequest,
)

router = APIRouter(tags=["Autenticación"])

ERROR_CREDENCIALES = "Usuario o contraseña incorrectos."


def _login_con_password(
    credenciales: LoginRequest,
    roles_permitidos: tuple[str, ...] | None = None,
) -> LoginResponse:
    """Valida usuario + contraseña y emite el token de personal.

    Si `roles_permitidos` se indica, la cuenta debe tener uno de esos roles.
    """
    username = credenciales.username.strip().lower()
    try:
        filas = (
            supabase.table("usuarios")
            .select("*")
            .eq("username", username)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("verificar las credenciales")

    if not filas or not filas[0].get("activo", True):
        fail(ERROR_CREDENCIALES, 401)
    cuenta = filas[0]
    if not verificar_secreto(credenciales.password, cuenta.get("password_hash")):
        fail(ERROR_CREDENCIALES, 401)
    if cuenta.get("rol") == "paciente":
        fail("Esta cuenta usa el portal del paciente (cédula y contraseña).", 403)
    if roles_permitidos is not None and cuenta.get("rol") not in roles_permitidos:
        fail("Esta cuenta no tiene acceso al panel institucional.", 403)

    nombre = cuenta.get("username")
    especialidad = None
    clinica_id = None
    personal_id = cuenta.get("personal_id")
    if personal_id:
        try:
            p = (
                supabase.table("personal")
                .select("id, nombre, apellido, especialidad, clinica_id")
                .eq("id", personal_id)
                .limit(1)
                .execute()
                .data
                or [{}]
            )[0]
            nombre = f"{p.get('nombre', '')} {p.get('apellido', '')}".strip() or nombre
            especialidad = p.get("especialidad")
            clinica_id = p.get("clinica_id")
        except Exception:
            pass

    token = crear_token(
        {
            "tipo": "staff",
            "rol": cuenta["rol"],
            "username": cuenta["username"],
            "personal_id": personal_id,
            "paciente_id": None,
            "cedula": "",
        }
    )
    registrar_accion(
        {"rol": cuenta["rol"], "username": cuenta["username"], "personal_id": personal_id},
        "login_staff",
        "usuarios",
        cuenta.get("id"),
        detalle=f"Rol {cuenta['rol']}",
    )
    return LoginResponse(
        token=token,
        usuario=LoginUsuarioResponse(
            username=cuenta["username"],
            rol=cuenta["rol"],
            nombre=nombre,
            especialidad=especialidad,
            clinica_id=clinica_id,
            personal_id=personal_id,
        ),
    )


@router.post("/login", response_model=LoginResponse)
def login(credenciales: LoginRequest) -> LoginResponse:
    """Inicia sesión del personal (rol: medico, farmaceutico, enfermero, superusuario)."""
    return _login_con_password(credenciales)


@router.post("/institucional", response_model=LoginResponse)
def login_institucional(credenciales: LoginRequest) -> LoginResponse:
    """Acceso al panel institucional: solo admin_sistemas y director."""
    return _login_con_password(credenciales, roles_permitidos=ROLES_GLOBALES)


@router.post("/paciente", response_model=PacienteLoginResponse)
def login_paciente(datos: PacienteLoginRequest) -> PacienteLoginResponse:
    """Acceso al portal del paciente: cédula + contraseña."""
    secreto = datos.password.strip()
    if not secreto:
        fail("Ingrese su contraseña.", 400)

    cedula = datos.cedula.strip()
    fila = _buscar_paciente(cedula)
    if not verificar_secreto(secreto, fila.get("pin_hash")):
        fail("Contraseña incorrecta. Verifique su cédula y su contraseña.", 401)

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
        "login_paciente",
        "historias_clinicas",
        fila["id"],
    )
    return PacienteLoginResponse(token=token, paciente=_a_historia(fila))


@router.post("/paciente/recuperar", response_model=RecuperarPasswordResponse)
def recuperar_password(datos: RecuperarPasswordRequest) -> RecuperarPasswordResponse:
    """Genera un código de 6 dígitos si la cédula y el correo coinciden.

    Sin SMTP configurado el código se envía igualmente por la respuesta solo
    en desarrollo (ENVIRONMENT != production); en producción va por correo.
    """
    fila = _buscar_paciente(datos.cedula.strip())
    email_registrado = (fila.get("email") or "").strip().lower()
    if not email_registrado or email_registrado != datos.email.strip().lower():
        fail("El correo no coincide con el registrado para esta cédula.")

    codigo = generar_codigo()
    minutos = settings.RECUPERACION_EXPIRACION_MINUTOS
    expira = datetime.now(timezone.utc) + timedelta(minutes=minutos)
    try:
        supabase.table("recuperacion_pacientes").insert(
            {
                "paciente_id": fila["id"],
                "codigo_hash": hash_secreto(codigo),
                "expira_en": expira.isoformat(),
            }
        ).execute()
    except Exception:
        db_fail("generar el código de recuperación")

    enviado = enviar_codigo_recuperacion(
        fila.get("nombre_completo", "Paciente"),
        codigo,
        minutos,
        fila["email"],
    )
    return RecuperarPasswordResponse(
        mensaje=(
            "Hemos enviado un código de 6 dígitos a su correo. "
            f"Válido por {minutos} minutos."
            if enviado
            else "Si el correo coincide con el registrado, recibirá un código "
            f"de 6 dígitos válido por {minutos} minutos."
        ),
        expira_minutos=minutos,
        codigo_desarrollo=None if (settings.es_produccion or enviado) else codigo,
    )


@router.post("/paciente/reset", response_model=HistoriaClinicaResponse)
def reset_password(datos: ResetPasswordRequest) -> HistoriaClinicaResponse:
    """Valida el código recibido y restablece la contraseña del paciente."""
    secreto = datos.password.strip()
    if not secreto:
        fail("Indique la nueva contraseña.")
    if not (6 <= len(secreto) <= 64):
        fail("La contraseña debe tener entre 6 y 64 caracteres.")

    fila = _buscar_paciente(datos.cedula.strip())
    ahora = datetime.now(timezone.utc)
    try:
        registros = (
            supabase.table("recuperacion_pacientes")
            .select("id, codigo_hash, expira_en")
            .eq("paciente_id", fila["id"])
            .eq("usado", False)
            .order("created_at", desc=True)
            .limit(5)
            .execute()
            .data
            or []
        )
    except Exception:
        db_fail("validar el código de recuperación")

    valido = None
    for registro in registros:
        try:
            expira = datetime.fromisoformat(str(registro["expira_en"]).replace("Z", "+00:00"))
        except Exception:
            continue
        if expira >= ahora and verificar_secreto(datos.codigo, registro.get("codigo_hash")):
            valido = registro
            break
    if not valido:
        fail("Código inválido o expirado. Solicite uno nuevo.")

    try:
        supabase.table("recuperacion_pacientes").update({"usado": True}).eq(
            "id", valido["id"]
        ).execute()
        supabase.table("historias_clinicas").update(
            {"pin_hash": hash_secreto(secreto)}
        ).eq("id", fila["id"]).execute()
    except Exception:
        db_fail("restablecer la contraseña")

    return _a_historia(fila)
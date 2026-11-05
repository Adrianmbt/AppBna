"""Dependencias de autenticación y autorización para la API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import Depends, Header, HTTPException, status

from app.core.security import verificar_token

ROLES_STAFF = ("superusuario", "medico", "farmaceutico", "enfermero")

# Cuentas globales del portal público (sin centro asignado): ven todos los
# centros de salud desde cualquier lugar.
ROLES_GLOBALES = ("admin_sistemas", "director")


def usuario_actual(
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Decodifica el JWT del header Authorization: Bearer <token>.

    Levanta 401 si falta el token o no es válido.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Debe iniciar sesión para acceder a este recurso.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = verificar_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Su sesión expiró. Vuelva a iniciar sesión.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def exigir_staff(usuario: Dict[str, Any] = Depends(usuario_actual)) -> Dict[str, Any]:
    """Cualquier rol del personal (no pacientes)."""
    if usuario.get("tipo") != "staff":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos para esta operación.",
        )
    return usuario


def exigir_roles(*roles: str):
    """Factory: exige que el rol del usuario esté en la lista dada."""
    def validador(usuario: Dict[str, Any] = Depends(exigir_staff)) -> Dict[str, Any]:
        if usuario.get("rol") not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Su rol no tiene permisos para esta operación.",
            )
        return usuario
    return validador


def exigir_rol_global(
    usuario: Dict[str, Any] = Depends(exigir_staff),
) -> Dict[str, Any]:
    """Solo las cuentas globales (admin_sistemas / director)."""
    if usuario.get("rol") not in ROLES_GLOBALES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta sección es exclusiva para el personal directivo.",
        )
    return usuario


def exigir_paciente(
    usuario: Dict[str, Any] = Depends(usuario_actual),
) -> Dict[str, Any]:
    """Solo el propio paciente (con su token del portal)."""
    if usuario.get("tipo") != "paciente":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta acción solo está disponible para el paciente.",
        )
    return usuario


def exigir_paciente_o_staff(
    cedula: str,
    usuario: Dict[str, Any] = Depends(usuario_actual),
) -> Dict[str, Any]:
    """Un paciente solo accede a su propia historia; el personal, a cualquiera."""
    if usuario.get("tipo") == "staff":
        return usuario
    if usuario.get("tipo") == "paciente" and usuario.get("cedula") == cedula:
        return usuario
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Solo puede consultar sus propios datos.",
    )

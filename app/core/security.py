"""Seguridad de BnaSalud: JWT, bcrypt y generación de códigos."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import bcrypt
import jwt

from app.core.config import settings


def hash_secreto(valor: str) -> str:
    """Hash bcrypt de un secreto (contraseña del paciente o del personal)."""
    return bcrypt.hashpw(valor.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_secreto(valor: str, hash_: str | None) -> bool:
    """Compara un valor contra su hash bcrypt (seguro ante hash nulos)."""
    if not hash_:
        return False
    try:
        return bcrypt.checkpw(valor.encode("utf-8"), hash_.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def crear_token(payload: Dict[str, Any], minutos: int | None = None) -> str:
    """Emite un JWT con expiración (default: configuración global)."""
    data = dict(payload)
    expiracion = timedelta(minutes=minutos or settings.JWT_EXPIRACION_MINUTOS)
    data["exp"] = datetime.now(timezone.utc) + expiracion
    data["iat"] = datetime.now(timezone.utc)
    return jwt.encode(data, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def verificar_token(token: str) -> Dict[str, Any]:
    """Valida y decodifica un JWT. Lanza jwt.PyJWTError si es inválido."""
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


def generar_codigo() -> str:
    """Código numérico de 6 dígitos para restablecer la contraseña."""
    return f"{secrets.randbelow(1_000_000):06d}"


def sesion_activa() -> Dict[str, Any]:
    """Payload base de una sesión autenticada."""
    return {
        "tipo": "",
        "rol": "",
        "username": "",
        "cedula": "",
        "personal_id": None,
        "paciente_id": None,
    }

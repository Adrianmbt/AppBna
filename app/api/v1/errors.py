"""Manejo de errores consistente para la API."""

from fastapi import HTTPException, status
from typing import NoReturn


def fail(detail: str, code: int = status.HTTP_400_BAD_REQUEST) -> NoReturn:
    """Levanta una HTTPException con formato consistente."""
    raise HTTPException(status_code=code, detail=detail)


def db_fail(accion: str) -> NoReturn:
    """Error genérico de base de datos (no filtrar detalles internos)."""
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"No se pudo {accion}. Intente nuevamente.",
    )


def not_found(recurso: str) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{recurso} no encontrado.",
    )

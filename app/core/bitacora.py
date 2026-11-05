"""Bitácora de acciones sensibles (Fase 7).

Cada acción relevante (login, cambios de estado de recetas, cola, resultados)
queda registrada en `bitacora_acciones` y se consulta desde /admin.
Nunca interrumpe el flujo principal: los fallos de registro se ignoran.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.core.database import supabase


def registrar_accion(
    usuario: Optional[Dict[str, Any]],
    accion: str,
    entidad: str = "",
    entidad_id: Any = None,
    detalle: str = "",
) -> bool:
    """Registra una acción del personal o paciente en la bitácora."""
    usuario = usuario or {}
    fila = {
        "usuario_id": usuario.get("personal_id"),
        "username": str(usuario.get("username") or "")[:80] or None,
        "rol": str(usuario.get("rol") or "")[:30] or None,
        "accion": accion[:60],
        "entidad": entidad[:40] or None,
        "entidad_id": str(entidad_id)[:80] if entidad_id is not None else None,
        "detalle": detalle or None,
    }
    try:
        supabase.table("bitacora_acciones").insert(fila).execute()
        return True
    except Exception:
        return False

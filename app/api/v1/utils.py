"""Utilidades compartidas de serialización para los endpoints."""

import json
from typing import Any, List


def parse_list(valor: Any) -> List[Any]:
    """Convierte a lista valores almacenados como TEXT-JSON, JSONB o ya-lista."""
    if valor is None:
        return []
    if isinstance(valor, list):
        return valor
    if isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            return []
        try:
            parsed = json.loads(texto)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        return [texto]
    return []


def parse_json_list(valor: Any) -> List[Any]:
    """Igual que parse_list, pero descarta elementos no-dict de listas de objetos."""
    items = parse_list(valor)
    return [i for i in items if isinstance(i, dict)]

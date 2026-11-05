"""Tarea programada (Fase 5): recordatorio de cita ~24 horas antes.

Un job por hora revisa las citas dentro de la ventana y envía los correos;
la tabla `notificaciones` evita duplicados si el servidor se reinicia.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.notificaciones import procesar_recordatorios

_programador: BackgroundScheduler | None = None


def _tarea_recordatorios() -> None:
    try:
        procesar_recordatorios(horas_antes=24)
    except Exception:
        logging.getLogger("bna.scheduler").exception(
            "Fallo la tarea de recordatorios de citas"
        )


def iniciar_programador() -> None:
    """Arranca el planificador (idempotente); primera pasada inmediata."""
    global _programador
    if _programador is not None:
        return
    _programador = BackgroundScheduler(timezone="UTC")
    _programador.add_job(
        _tarea_recordatorios,
        IntervalTrigger(hours=1),
        id="recordatorio_citas",
        next_run_time=datetime.now(timezone.utc),
    )
    _programador.start()


def detener_programador() -> None:
    global _programador
    if _programador is not None:
        _programador.shutdown(wait=False)
        _programador = None

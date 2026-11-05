"""Correos por SMTP (Fase 3 y 5): bienvenida, restablecimiento de contraseña,
aviso de receta entregada, recordatorio de cita y avisos del personal.

Si no hay SMTP configurado en .env, las funciones devuelven False; en
desarrollo la API expone el código para poder probar el flujo sin correo.
"""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List

from app.core.config import settings


def smtp_habilitado() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_PORT)


def _plantilla_bienvenida(nombre: str, cedula: str) -> str:
    return f"""
    <div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:0 auto;background:#f6f7f9;border-radius:16px;overflow:hidden;border:1px solid #e2e5ea">
      <div style="background:linear-gradient(135deg,#0b3d91,#1d4ed8);padding:22px 26px;color:#fff">
        <p style="margin:0;font-size:13px;letter-spacing:2px;opacity:.85">BNA SALUD · RED DE SALUD</p>
        <h1 style="margin:6px 0 0;font-size:20px">¡Bienvenido, {nombre}!</h1>
      </div>
      <div style="padding:24px 26px">
        <p style="margin:0 0 14px;color:#374151;font-size:14px;line-height:1.6">
          Tu historia clínica fue creada en la red. En el <b>Portal del Paciente</b>
          puedes ver tus citas, tus estudios y tus recetas.
        </p>
        <div style="background:#fff;border:1px dashed #1d4ed8;border-radius:12px;padding:16px 20px;margin:14px 0">
          <p style="margin:0 0 6px;font-size:11px;letter-spacing:1px;color:#6b7280">CÉDULA</p>
          <p style="margin:0;font-size:16px;font-weight:700;color:#0b3d91">{cedula}</p>
        </div>
        <p style="margin:0;color:#6b7280;font-size:12px;line-height:1.6">
          Para entrar, crea tu contraseña en la pantalla de acceso con
          «¿Olvidaste tu contraseña?»: te enviamos un código a este correo y la
          eliges tú. Nadie de BNA Salud te pedirá tu contraseña por teléfono ni por correo.
        </p>
      </div>
      <div style="padding:12px 26px;background:#eef1f6;font-size:11px;color:#9aa3b2">
        Correo automático del Sistema de Salud Barcelona. No respondas a este mensaje.
      </div>
    </div>
    """


def _plantilla_codigo(nombre: str, codigo: str, minutos: int) -> str:
    return f"""
    <div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:0 auto;background:#f6f7f9;border-radius:16px;overflow:hidden;border:1px solid #e2e5ea">
      <div style="background:linear-gradient(135deg,#0b3d91,#1d4ed8);padding:22px 26px;color:#fff">
        <p style="margin:0;font-size:13px;letter-spacing:2px;opacity:.85">BNA SALUD · NUEVA CONTRASEÑA</p>
        <h1 style="margin:6px 0 0;font-size:20px">Hola, {nombre}</h1>
      </div>
      <div style="padding:24px 26px">
        <p style="margin:0 0 14px;color:#374151;font-size:14px;line-height:1.6">
          Recibimos una solicitud para restablecer tu contraseña del portal.
          Usa este código:
        </p>
        <div style="background:#fff;border:1px dashed #1d4ed8;border-radius:12px;padding:16px;text-align:center;margin:14px 0">
          <p style="margin:0;font-size:30px;font-weight:800;letter-spacing:10px;color:#1d4ed8">{codigo}</p>
        </div>
        <p style="margin:0;color:#6b7280;font-size:12px;line-height:1.6">
          El código expira en <b>{minutos} minutos</b>. Si no solicitaste este cambio,
          ignora este mensaje; tu contraseña actual sigue siendo válida.
        </p>
      </div>
      <div style="padding:12px 26px;background:#eef1f6;font-size:11px;color:#9aa3b2">
        Correo automático del Sistema de Salud Barcelona. No respondas a este mensaje.
      </div>
    </div>
    """


def _cuerpo(titulo: str, parrafos: List[str], pie: str = "") -> str:
    """Arma el cuerpo estándar de los correos de la Fase 5."""
    filas = "".join(
        f'<p style="margin:0 0 14px;color:#374151;font-size:14px;line-height:1.6">{p}</p>'
        for p in parrafos
        if p
    )
    return f"""
    <div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:0 auto;background:#f6f7f9;border-radius:16px;overflow:hidden;border:1px solid #e2e5ea">
      <div style="background:linear-gradient(135deg,#0b3d91,#1d4ed8);padding:22px 26px;color:#fff">
        <p style="margin:0;font-size:13px;letter-spacing:2px;opacity:.85">BNA SALUD · RED DE SALUD</p>
        <h1 style="margin:6px 0 0;font-size:20px">{titulo}</h1>
      </div>
      <div style="padding:24px 26px">{filas}</div>
      <div style="padding:12px 26px;background:#eef1f6;font-size:11px;color:#9aa3b2">
        {pie or "Correo automático del Sistema de Salud Barcelona. No respondas a este mensaje."}
      </div>
    </div>
    """


def _plantilla_receta_entregada(nombre: str, codigo: str) -> str:
    return _cuerpo(
        f"Tu receta {codigo} está lista",
        [
            f"Hola, {nombre}. La farmacia registró la entrega de tu receta "
            f"<b>{codigo}</b>: tus medicamentos ya fueron despachados.",
            "Entra al <b>Portal del Paciente</b> y confirma la recepción para "
            "cerrar el ciclo de la receta.",
            "Si no fuiste quien retiró los medicamentos, avísale de inmediato "
            "al personal de la farmacia de tu centro.",
        ],
    )


def _plantilla_recordatorio_cita(
    nombre: str, fecha_larga: str, hora: str, centro: str, especialidad: str
) -> str:
    return _cuerpo(
        "Recordatorio: tienes una cita mañana",
        [
            f"Hola, {nombre}. Te recordamos tu cita médica:",
            '<div style="background:#fff;border:1px dashed #1d4ed8;border-radius:12px;'
            'padding:16px 20px;margin:14px 0">'
            '<p style="margin:0 0 6px;font-size:11px;letter-spacing:1px;color:#6b7280">FECHA</p>'
            '<p style="margin:0;font-size:15px;font-weight:700;color:#0b3d91;text-transform:capitalize">'
            f"{fecha_larga}</p>"
            '<p style="margin:12px 0 6px;font-size:11px;letter-spacing:1px;color:#6b7280">HORA</p>'
            '<p style="margin:0;font-size:22px;font-weight:800;color:#1d4ed8">'
            f"{hora}</p>"
            f'<p style="margin:12px 0 0;font-size:13px;color:#374151">{especialidad} · {centro}</p></div>',
            "Llega 15 minutos antes con tu cédula. Si no puedes asistir, "
            "cancela o reprograma desde el portal del paciente.",
        ],
    )


def _plantilla_resultados(nombre: str, comprobante: str, estudios: int) -> str:
    return _cuerpo(
        "Tus resultados están disponibles",
        [
            f"Hola, {nombre}. Ya fueron cargados los resultados de tu estudio"
            + (f" (orden <b>{comprobante}</b>)" if comprobante else "")
            + f" — {estudios} informe(s) listo(s) para consultar.",
            "Entra al <b>Portal del Paciente</b>, sección <b>Estudios</b>, "
            "para verlos junto con su fecha de entrega.",
            "Lleva estos resultados a tu próxima consulta para la revisión médica.",
        ],
    )


def enviar_correo(destinatario: str, asunto: str, html: str) -> bool:
    """Envía un correo HTML por SMTP. Devuelve False en modo demo o si falla."""
    if not smtp_habilitado() or not (destinatario or "").strip():
        return False
    try:
        mensaje = MIMEMultipart("alternative")
        mensaje["Subject"] = asunto
        mensaje["From"] = settings.SMTP_FROM or settings.SMTP_USER or "no-reply@bnasalud.local"
        mensaje["To"] = destinatario.strip()
        mensaje.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as servidor:
            if settings.SMTP_USE_TLS:
                servidor.starttls()
            if settings.SMTP_USER:
                servidor.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
            servidor.sendmail(mensaje["From"], [mensaje["To"]], mensaje.as_string())
        return True
    except Exception:
        return False


def enviar_bienvenida(nombre: str, cedula: str, email: str) -> bool:
    """Tarjeta de bienvenida al paciente recién registrado."""
    return enviar_correo(
        email,
        "¡Bienvenido a BNA Salud! Ya puedes crear tu contraseña del portal",
        _plantilla_bienvenida(nombre, cedula),
    )


def enviar_codigo_recuperacion(nombre: str, codigo: str, minutos: int, email: str) -> bool:
    """Código de 6 dígitos para restablecer la contraseña del portal."""
    return enviar_correo(
        email,
        "Nueva contraseña del portal — BNA Salud",
        _plantilla_codigo(nombre, codigo, minutos),
    )


def enviar_receta_entregada(nombre: str, codigo: str, email: str) -> bool:
    """Aviso al paciente cuando la farmacia registra la entrega (Fase 5)."""
    return enviar_correo(
        email,
        f"Receta {codigo} entregada — confirma en tu portal",
        _plantilla_receta_entregada(nombre, codigo),
    )


def enviar_recordatorio_cita(
    nombre: str, fecha_larga: str, hora: str, centro: str, especialidad: str, email: str
) -> bool:
    """Recordatorio de cita ~24 horas antes (tarea programada)."""
    return enviar_correo(
        email,
        "Recordatorio de tu cita médica — BNA Salud",
        _plantilla_recordatorio_cita(nombre, fecha_larga, hora, centro, especialidad),
    )


def enviar_aviso_personal(nombre: str, titulo: str, mensaje_html: str, email: str) -> bool:
    """Aviso genérico enviado por el personal autorizado (POST /pacientes/notificar)."""
    return enviar_correo(
        email,
        f"{titulo} — BNA Salud",
        _cuerpo(titulo, [f"Hola, {nombre}.", mensaje_html]),
    )


def enviar_resultados_disponibles(
    nombre: str, comprobante: str, cantidad_estudios: int, email: str
) -> bool:
    """Aviso al paciente cuando su orden de estudios tiene resultados (Fase 6)."""
    return enviar_correo(
        email,
        "Resultados de estudios disponibles — BNA Salud",
        _plantilla_resultados(nombre, comprobante, cantidad_estudios),
    )
"""Avisos por correo (Gmail) al titular sobre solicitudes de eliminación: fallidas, con el
plazo de 7 días próximo o ya vencido.

El mensaje lleva SOLO el número de solicitud, el estado, las fechas y los intentos: nunca el
id de la persona ni contenido. Sin credenciales configuradas `send_alert` no envía nada y
devuelve False, así que privacy_requests.dispatch_alerts deja el aviso pendiente y lo
reintenta cuando haya configuración (la solicitud se procesa igual).

Variables de entorno (nombres; los valores viven en el .env y los introduce el titular con
deploy/set_privacy_alert_credentials.sh, nunca por una conversación):
  PRIVACY_ALERT_SMTP_USER      cuenta Gmail que envía
  PRIVACY_ALERT_SMTP_PASSWORD  contraseña de aplicación de esa cuenta (no la de acceso)
  PRIVACY_ALERT_TO             destinatario (por defecto, la misma cuenta)
  PRIVACY_ALERT_SMTP_HOST      opcional, por defecto smtp.gmail.com (puerto 465, SSL)
"""

import asyncio
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger(__name__)

_SUBJECTS = {
    "failed": "falló el procesamiento de una solicitud de eliminación",
    "due_soon": "solicitud de eliminación próxima a vencer (menos de 48 h)",
    "overdue": "solicitud de eliminación VENCIDA (plazo de 7 días superado)",
}


def _settings() -> dict | None:
    user = os.getenv("PRIVACY_ALERT_SMTP_USER", "").strip()
    password = os.getenv("PRIVACY_ALERT_SMTP_PASSWORD", "")
    if not user or not password:
        return None
    return {
        "user": user,
        "password": password,
        "to": os.getenv("PRIVACY_ALERT_TO", "").strip() or user,
        "host": os.getenv("PRIVACY_ALERT_SMTP_HOST", "").strip() or "smtp.gmail.com",
    }


def configured() -> bool:
    return _settings() is not None


def format_alert(alert: dict) -> tuple[str, str]:
    """(asunto, cuerpo) de un aviso de privacy_requests.pending_alerts. Sin ids de persona."""
    subject = f"[Purgito] {_SUBJECTS[alert['kind']]} (#{alert['id']})"
    body = (
        f"Solicitud #{alert['id']} ({alert['kind']})\n"
        f"Estado: {alert['status']}\n"
        f"Creada: {alert['created_at']} UTC\n"
        f"Vence: {alert['due_at']} UTC\n"
        f"Intentos: {alert['attempts']}\n"
        f"Último error: {alert.get('last_error') or '-'}\n\n"
        "Consulta el registro de la solicitud (privacy_request_log) en la base. "
        "Este mensaje no incluye datos de la persona."
    )
    return subject, body


def _send_sync(cfg: dict, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = cfg["user"]
    msg["To"] = cfg["to"]
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP_SSL(
        cfg["host"], 465, context=ssl.create_default_context(), timeout=20
    ) as smtp:
        smtp.login(cfg["user"], cfg["password"])
        smtp.send_message(msg)


async def send_alert(alert: dict) -> bool:
    """True solo si el correo salió. Nunca lanza ni registra la contraseña."""
    cfg = _settings()
    if cfg is None:
        log.warning(
            "privacy_alerts: sin credenciales de correo; el aviso queda pendiente"
        )
        return False
    subject, body = format_alert(alert)
    try:
        await asyncio.to_thread(_send_sync, cfg, subject, body)
    except Exception as e:
        # Solo el tipo: el mensaje de smtplib puede repetir el usuario o el servidor.
        log.error("privacy_alerts: no se pudo enviar el aviso (%s)", type(e).__name__)
        return False
    return True

"""Privacidad: trabajador de fondo del Centro de Privacidad.

La gestión de datos personales (descargar, pedir la eliminación, excluirse del aprendizaje, consultar
el estado y solicitar otros derechos) se hace SOLO desde https://purgito.app/privacidad con la sesión
de Discord; este cog ya no registra comandos de barra. Solo procesa las solicitudes de eliminación
pendientes y envía los avisos al titular (ver privacy_requests y privacy_alerts)."""

import logging

from discord.ext import commands, tasks

import generation
import privacy_alerts
import privacy_guard
import privacy_requests
import privacy_rights
from observability import events as obs_events

log = logging.getLogger(__name__)

# Aviso -> (evento interno, severidad). El mensaje no lleva ids de persona; solo el número de solicitud.
# Emite (el nombre se pasa por variable; tests/test_obs_events.py lo busca por este formato):
# event=privacy.request_failed event=privacy.request_due_soon event=privacy.request_overdue
_ALERT_EVENTS = {
    "failed": ("privacy.request_failed", "error", "falló un intento y se reintenta"),
    "due_soon": ("privacy.request_due_soon", "warning", "vence en menos de 48 h"),
    "overdue": ("privacy.request_overdue", "critical", "SUPERÓ su plazo de 7 días"),
}


async def _send_alert(alert: dict) -> bool:
    """Reutiliza Purgito Monitor (Discord) y, si hay credenciales, también el correo. Cuenta como
    enviado si salió por alguno de los dos canales; el evento solo se emite si el monitor está activo."""
    name, severity, text = _ALERT_EVENTS[alert["kind"]]
    ok = False
    try:
        obs_events.log_event(
            name,
            severity=severity,
            message=f"Privacidad: la solicitud de eliminación #{alert['id']} {text} "
            f"(vence {alert['due_at']} UTC, intentos {alert['attempts']}).",
            request_number=alert["id"],
        )
        ok = True
    except Exception:
        log.exception("privacy_worker: no se pudo emitir el aviso al monitor")
    if privacy_alerts.configured():
        ok = await privacy_alerts.send_alert(alert) or ok
    return ok


class Privacy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._worker_cycles = 0

    async def cog_load(self) -> None:
        self.privacy_worker.start()

    async def cog_unload(self) -> None:
        self.privacy_worker.cancel()

    @tasks.loop(seconds=60)
    async def privacy_worker(self) -> None:
        """Procesa las solicitudes de eliminación del Centro de Privacidad (API) y envía los
        avisos pendientes. Todo el estado vive en la base: si el bot se reinicia, el próximo
        ciclo retoma lo que haya quedado (ver privacy_requests)."""
        try:
            await privacy_guard.beat()
        except Exception:
            log.exception("privacy_worker: no se pudo escribir el latido")
        try:
            await privacy_requests.process_due(generation.forget_user)
            await privacy_requests.dispatch_alerts(_send_alert)
            self._worker_cycles += 1
            if self._worker_cycles % 60 == 1:
                await privacy_requests.purge_old()
                await privacy_rights.purge_old()
            if self._worker_cycles % 1440 == 1:
                overdue = [
                    r for r in await privacy_rights.open_requests() if r["overdue"]
                ]
                if overdue:
                    obs_events.log_event(
                        "privacy.rights_overdue",
                        message=f"Privacidad: {len(overdue)} solicitud(es) de derechos sin contestar "
                        f"fuera de plazo (ids {','.join(str(r['id']) for r in overdue[:10])}). "
                        "Ver scripts/privacy_inbox.py list.",
                        overdue=len(overdue),
                    )
                    log.error(
                        "privacy.rights: %d solicitud(es) de derechos VENCIDA(S) sin contestar "
                        "(ids %s); ver scripts/privacy_inbox.py list",
                        len(overdue),
                        ",".join(str(r["id"]) for r in overdue[:10]),
                    )
        except Exception:
            log.exception("privacy_worker: ciclo fallido; se reintenta en el siguiente")

    @privacy_worker.before_loop
    async def _before_privacy_worker(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Privacy(bot))

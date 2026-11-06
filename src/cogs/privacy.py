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

log = logging.getLogger(__name__)


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
            if privacy_alerts.configured():
                await privacy_requests.dispatch_alerts(privacy_alerts.send_alert)
            self._worker_cycles += 1
            if self._worker_cycles % 60 == 1:
                await privacy_requests.purge_old()
                await privacy_rights.purge_old()
                overdue = [r for r in await privacy_rights.open_requests() if r["overdue"]]
                if overdue:
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

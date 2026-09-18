"""Los 7 @tasks.loop periódicos del bot (RSS, YouTube, Twitch, cupos,
anuncios x2, meme automático) mueren para siempre ante cualquier excepción
que discord.ext.tasks no reintente por su cuenta (ver
Loop._valid_exception: solo cubre errores de red/gateway) -- sin un
@loop.error que llame a .restart(), un sqlite3.OperationalError transitorio
apaga la feature sin ningún aviso visible hasta que un admin note que dejó
de avisar. Estos tests verifican que cada loop tiene ese handler y que
efectivamente reinicia el loop en vez de solo loguear."""

import asyncio
from types import SimpleNamespace

import pytest

import cogs.anuncios as anuncios_mod
import cogs.memes as memes_mod
import cogs.quota_alerts as quota_alerts_mod
import cogs.rss as rss_mod
import cogs.twitch as twitch_mod
import cogs.youtube as youtube_mod

_CASES = [
    (rss_mod.RSS, "check_rss"),
    (youtube_mod.YouTube, "check_youtube"),
    (twitch_mod.Twitch, "check_twitch"),
    (quota_alerts_mod.QuotaAlerts, "check_quotas"),
    (anuncios_mod.Anuncios, "check_announcements"),
    (anuncios_mod.Anuncios, "sweep_pending_deletions"),
    (memes_mod.Memes, "auto_meme_task"),
]


@pytest.mark.parametrize("cog_cls, loop_name", _CASES, ids=[c[1] for c in _CASES])
def test_error_handler_reinicia_el_loop(cog_cls, loop_name, monkeypatch):
    cog = cog_cls(SimpleNamespace())
    loop = getattr(cog, loop_name)
    assert loop._error is not None, (
        f"{loop_name} no tiene un @{loop_name}.error registrado"
    )

    restarted = []
    monkeypatch.setattr(loop, "restart", lambda *a, **k: restarted.append(True))

    asyncio.run(loop._error(cog, RuntimeError("boom")))

    assert restarted == [True]

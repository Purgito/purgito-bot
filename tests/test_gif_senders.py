"""Tests de gif_senders: quién mandó cada GIF y en qué mensaje, usado por el
catálogo por persona del panel y el link "ir al mensaje" del catálogo general.

Mismo estilo que test_gif_dedup.py: SQLite en memoria inyectada en db._db,
sin tocar data/bot.db ni R2 real.
"""

import asyncio

import aiosqlite
import pytest

import db

_GUILD = 1
_OTHER_GUILD = 2
_USER_A = 111
_USER_B = 222


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    yield conn
    asyncio.run(conn.close())


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    return conn


async def _senders_rows(conn, gif_id):
    async with conn.execute(
        "SELECT user_id, channel_id, message_id, send_count FROM gif_senders "
        "WHERE gif_id=? ORDER BY user_id",
        (gif_id,),
    ) as cur:
        return await cur.fetchall()


def test_save_gif_url_sin_user_id_no_registra_remitente(memory_db):
    async def run():
        await db.save_gif_url(_GUILD, "https://tenor.com/view/a-1")
        gif = await db.get_gif_by_url(_GUILD, "https://tenor.com/view/a-1")
        assert await _senders_rows(memory_db, gif["id"]) == []

    asyncio.run(run())


def test_save_gif_url_registra_remitente_y_mensaje(memory_db):
    async def run():
        await db.save_gif_url(
            _GUILD,
            "https://tenor.com/view/a-1",
            user_id=_USER_A,
            channel_id=50,
            message_id=500,
        )
        gif = await db.get_gif_by_url(_GUILD, "https://tenor.com/view/a-1")
        rows = await _senders_rows(memory_db, gif["id"])
        assert rows == [(_USER_A, 50, 500, 1)]

    asyncio.run(run())


def test_reenvio_del_mismo_usuario_suma_send_count_y_actualiza_mensaje(memory_db):
    async def run():
        url = "https://tenor.com/view/a-1"
        await db.save_gif_url(
            _GUILD, url, user_id=_USER_A, channel_id=50, message_id=500
        )
        # Mismo GIF, mismo usuario, mensaje distinto (lo volvió a mandar).
        await db.save_gif_url(
            _GUILD, url, user_id=_USER_A, channel_id=51, message_id=999
        )
        gif = await db.get_gif_by_url(_GUILD, url)
        rows = await _senders_rows(memory_db, gif["id"])
        # Una sola fila (no una por envío): canal/mensaje del más reciente, contador en 2.
        assert rows == [(_USER_A, 51, 999, 2)]

    asyncio.run(run())


def test_dos_usuarios_distintos_comparten_el_mismo_gif(memory_db):
    async def run():
        url = "https://tenor.com/view/a-1"
        await db.save_gif_url(
            _GUILD, url, user_id=_USER_A, channel_id=50, message_id=500
        )
        # El GIF ya existía (mismo url, mismo guild) -- otra persona también lo mandó.
        inserted, _ = await db.save_gif_url(
            _GUILD, url, user_id=_USER_B, channel_id=52, message_id=700
        )
        assert inserted is False  # corpus_gifs no inserta de nuevo
        gif = await db.get_gif_by_url(_GUILD, url)
        rows = await _senders_rows(memory_db, gif["id"])
        assert rows == [(_USER_A, 50, 500, 1), (_USER_B, 52, 700, 1)]

    asyncio.run(run())


def test_alta_manual_sin_mensaje_deja_channel_y_message_null(memory_db):
    async def run():
        await db.save_gif_url(_GUILD, "https://tenor.com/view/a-1", user_id=_USER_A)
        gif = await db.get_gif_by_url(_GUILD, "https://tenor.com/view/a-1")
        rows = await _senders_rows(memory_db, gif["id"])
        assert rows == [(_USER_A, None, None, 1)]

    asyncio.run(run())


def test_delete_gif_url_by_id_borra_sus_remitentes(memory_db):
    async def run():
        await db.save_gif_url(
            _GUILD,
            "https://tenor.com/view/a-1",
            user_id=_USER_A,
            channel_id=1,
            message_id=1,
        )
        gif = await db.get_gif_by_url(_GUILD, "https://tenor.com/view/a-1")
        assert await db.delete_gif_url_by_id(_GUILD, gif["id"]) is True
        assert await _senders_rows(memory_db, gif["id"]) == []

    asyncio.run(run())


def test_block_gif_borra_sus_remitentes(memory_db):
    async def run():
        await db.save_gif_url(
            _GUILD,
            "https://tenor.com/view/a-1",
            user_id=_USER_A,
            channel_id=1,
            message_id=1,
        )
        gif = await db.get_gif_by_url(_GUILD, "https://tenor.com/view/a-1")
        await db.block_gif(_GUILD, None, "https://tenor.com/view/a-1")
        assert await _senders_rows(memory_db, gif["id"]) == []

    asyncio.run(run())


def test_wipe_gifs_borra_remitentes_del_guild(memory_db):
    async def run():
        await db.save_gif_url(
            _GUILD,
            "https://tenor.com/view/a-1",
            user_id=_USER_A,
            channel_id=1,
            message_id=1,
        )
        gif = await db.get_gif_by_url(_GUILD, "https://tenor.com/view/a-1")
        assert await db.wipe_gifs(_GUILD) == 1
        assert await _senders_rows(memory_db, gif["id"]) == []

    asyncio.run(run())


def test_auto_borrado_por_dead_streak_limpia_remitentes(memory_db):
    async def run():
        await db.save_gif_url(
            _GUILD,
            "https://tenor.com/view/a-1",
            user_id=_USER_A,
            channel_id=1,
            message_id=1,
        )
        gif = await db.get_gif_by_url(_GUILD, "https://tenor.com/view/a-1")
        assert await db.record_gif_health_check(gif["id"], "dead") is False
        assert await db.record_gif_health_check(gif["id"], "dead") is False
        assert await db.record_gif_health_check(gif["id"], "dead") is True
        assert await _senders_rows(memory_db, gif["id"]) == []

    asyncio.run(run())


def test_list_gif_senders_summary_ordena_por_cantidad_de_gifs(memory_db):
    async def run():
        await db.save_gif_url(_GUILD, "https://tenor.com/view/a-1", user_id=_USER_A)
        await db.save_gif_url(_GUILD, "https://tenor.com/view/a-2", user_id=_USER_A)
        await db.save_gif_url(_GUILD, "https://tenor.com/view/a-3", user_id=_USER_B)

        summary = await db.list_gif_senders_summary(_GUILD)
        assert summary == [
            {"user_id": _USER_A, "gif_count": 2},
            {"user_id": _USER_B, "gif_count": 1},
        ]

    asyncio.run(run())


def test_list_gif_senders_summary_no_mezcla_guilds(memory_db):
    async def run():
        await db.save_gif_url(_GUILD, "https://tenor.com/view/a-1", user_id=_USER_A)
        await db.save_gif_url(
            _OTHER_GUILD, "https://tenor.com/view/b-1", user_id=_USER_A
        )

        summary = await db.list_gif_senders_summary(_GUILD)
        assert summary == [{"user_id": _USER_A, "gif_count": 1}]

    asyncio.run(run())


def test_list_gifs_by_user_incluye_mensaje_y_contador(memory_db):
    async def run():
        await db.save_gif_url(
            _GUILD,
            "https://tenor.com/view/a-1",
            user_id=_USER_A,
            channel_id=1,
            message_id=1,
        )
        await db.save_gif_url(
            _GUILD,
            "https://tenor.com/view/a-1",
            user_id=_USER_A,
            channel_id=2,
            message_id=2,
        )
        await db.save_gif_url(_GUILD, "https://tenor.com/view/a-2", user_id=_USER_B)

        gifs = await db.list_gifs_by_user(_GUILD, _USER_A)
        assert len(gifs) == 1
        assert gifs[0]["url"] == "https://tenor.com/view/a-1"
        assert gifs[0]["channel_id"] == 2
        assert gifs[0]["message_id"] == 2
        assert gifs[0]["send_count"] == 2

    asyncio.run(run())


def test_list_gif_senders_by_guild_agrupa_por_gif(memory_db):
    async def run():
        await db.save_gif_url(
            _GUILD,
            "https://tenor.com/view/a-1",
            user_id=_USER_A,
            channel_id=1,
            message_id=1,
        )
        await db.save_gif_url(
            _GUILD,
            "https://tenor.com/view/a-1",
            user_id=_USER_B,
            channel_id=2,
            message_id=2,
        )
        gif = await db.get_gif_by_url(_GUILD, "https://tenor.com/view/a-1")

        by_gif = await db.list_gif_senders_by_guild(_GUILD)
        senders = {s["user_id"] for s in by_gif[gif["id"]]}
        assert senders == {_USER_A, _USER_B}

    asyncio.run(run())


def test_gif_bloqueado_no_registra_remitente(memory_db):
    async def run():
        url = "https://tenor.com/view/a-1"
        await db.block_gif(_GUILD, None, url)
        inserted, _ = await db.save_gif_url(_GUILD, url, user_id=_USER_A)
        assert inserted is False
        assert await db.get_gif_by_url(_GUILD, url) is None

    asyncio.run(run())


def test_fallo_al_registrar_remitente_no_tira_abajo_el_guardado_del_gif(memory_db):
    """Registrar el remitente es un enriquecimiento sobre el guardado, no el
    guardado en sí: si esa escritura falla por lo que sea (acá se fuerza
    borrando la tabla), el GIF tiene que quedar guardado en corpus_gifs
    igual -- no todo-o-nada por culpa de la atribución.

    Regresión real: antes de aislar el try/except, cualquier excepción sin
    atrapar en este punto hacía que _RollbackOnErrorLock deshaga TODA la
    transacción de save_gif_url, incluido el INSERT de corpus_gifs que ya
    había salido bien."""

    async def run():
        await memory_db.execute("DROP TABLE gif_senders")
        await memory_db.commit()

        inserted, _ = await db.save_gif_url(
            _GUILD,
            "https://tenor.com/view/a-1",
            user_id=_USER_A,
            channel_id=1,
            message_id=1,
        )
        assert inserted is True
        assert await db.get_gif_by_url(_GUILD, "https://tenor.com/view/a-1") is not None

    asyncio.run(run())


def test_wipe_gifs_resetea_el_checkpoint_de_refeed_del_guild(memory_db):
    """channel_refeed_status es el checkpoint de /refeed (desde qué mensaje en
    adelante ya está todo aprendido) -- es del corpus de TEXTO, ajeno a los
    GIFs. Si sobrevive a wipe_gifs, /refeed solo mira mensajes nuevos desde
    ahí y nunca vuelve a caminar el historial viejo donde quedaron los GIFs
    recién borrados, aunque sus links sigan vivos. wipe_gifs tiene que
    resetear el checkpoint de ESE guild (sin tocar el de otros) para que el
    próximo /refeed haga un backfill completo de nuevo."""

    async def run():
        await db.upsert_channel_refeed_status(
            _GUILD,
            10,
            newest_message_id=999,
            oldest_message_id=1,
            backfill_complete=True,
        )
        await db.upsert_channel_refeed_status(
            _OTHER_GUILD,
            20,
            newest_message_id=999,
            oldest_message_id=1,
            backfill_complete=True,
        )

        await db.save_gif_url(_GUILD, "https://tenor.com/view/a-1", user_id=_USER_A)
        await db.wipe_gifs(_GUILD)

        assert await db.get_channel_refeed_status(_GUILD, 10) is None
        # No debe tocar el checkpoint de otros guilds.
        assert await db.get_channel_refeed_status(_OTHER_GUILD, 20) is not None

    asyncio.run(run())

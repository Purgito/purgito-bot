"""purge_guild_data es lo que borra los datos de un servidor a los 30 días de
que el bot sale. La política de privacidad promete que se borran "por
completo", pero la lista de tablas era una copia a mano del schema: se habían
colado afuera gif_senders (user_id + canal + mensaje de quien mandó cada GIF),
gif_blocklist, guild_bot_style y embed_uploaded_images.

El primer test es el que evita que vuelva a pasar: compara la lista contra el
SCHEMA real, así que una tabla nueva con `guild_id` que nadie agregue a
_GUILD_PURGE_TABLES hace fallar la suite."""

import asyncio
import re

import pytest

import db
import r2
from cogs.general import General


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


def _tables_with_guild_id() -> set[str]:
    tables = set()
    for m in re.finditer(
        r"CREATE TABLE(?: IF NOT EXISTS)? (\w+) \((.*?)\n\);", db.SCHEMA, re.S
    ):
        if re.search(r"\bguild_id\b", m.group(2)):
            tables.add(m.group(1))
    return tables


def test_toda_tabla_con_guild_id_esta_en_la_lista_de_purga():
    faltan = _tables_with_guild_id() - set(db._GUILD_PURGE_TABLES)
    assert not faltan, (
        f"tablas con guild_id que purge_guild_data NO borra: {sorted(faltan)}. "
        "Agrégalas a db._GUILD_PURGE_TABLES."
    )


def test_la_lista_de_purga_no_tiene_tablas_inexistentes_ni_repetidas():
    en_schema = {
        m.group(1)
        for m in re.finditer(r"CREATE TABLE(?: IF NOT EXISTS)? (\w+) \(", db.SCHEMA)
    }
    assert set(db._GUILD_PURGE_TABLES) <= en_schema
    assert len(db._GUILD_PURGE_TABLES) == len(set(db._GUILD_PURGE_TABLES))


def test_las_cuatro_tablas_que_se_habian_colado_ahora_se_purgan():
    for tabla in (
        "gif_senders",
        "gif_blocklist",
        "guild_bot_style",
        "embed_uploaded_images",
    ):
        assert tabla in db._GUILD_PURGE_TABLES


def test_purge_borra_solo_el_guild_pedido(temp_db):
    async def run():
        conn = await db.get_db()
        for gid in (111, 222):
            await conn.execute(
                "INSERT INTO gif_senders (gif_id, guild_id, user_id, channel_id, message_id) "
                "VALUES (?, ?, 7, 1, 2)",
                (gid, gid),
            )
            await conn.execute(
                "INSERT INTO gif_blocklist (guild_id, content_hash, url, blocked_at) "
                "VALUES (?, 'h', 'u', 'now')",
                (gid,),
            )
            await conn.execute(
                "INSERT INTO guild_bot_style (guild_id, nick) VALUES (?, 'x')", (gid,)
            )
            await conn.execute(
                "INSERT INTO embed_uploaded_images (guild_id, url) VALUES (?, 'https://a/b.png')",
                (gid,),
            )
        await conn.commit()

        await db.purge_guild_data(111)

        restos = {}
        for tabla in (
            "gif_senders",
            "gif_blocklist",
            "guild_bot_style",
            "embed_uploaded_images",
        ):
            async with conn.execute(
                f"SELECT guild_id FROM {tabla}"  # noqa: S608 -- nombres fijos del test
            ) as cur:
                restos[tabla] = [r[0] for r in await cur.fetchall()]
        return restos

    restos = asyncio.run(run())
    for tabla, guilds in restos.items():
        assert guilds == [222], f"{tabla}: quedó {guilds}"


def test_list_uploaded_image_urls_devuelve_todas_no_solo_las_recientes(temp_db):
    async def run():
        for i in range(60):
            await db.record_uploaded_image(5, f"https://cdn.example.com/5/{i}.png")
        await db.record_uploaded_image(6, "https://cdn.example.com/6/x.png")
        return (
            await db.list_uploaded_image_urls(5),
            await db.list_uploaded_images(5),
        )

    todas, galeria = asyncio.run(run())
    assert len(todas) == 60
    assert len(galeria) == 40  # la galería del editor sigue truncada


# ── limpieza en R2 al salir de un servidor ───────────────────────────────────


class _FakeBot:
    def get_guild(self, guild_id):
        return None


def test_guild_cleanup_borra_de_r2_las_imagenes_subidas_desde_el_panel(
    temp_db, monkeypatch
):
    borradas = []

    async def fake_delete_url(url):
        borradas.append(url)

    monkeypatch.setattr(r2, "gifs_available", lambda: True)
    monkeypatch.setattr(r2, "images_available", lambda: True)
    monkeypatch.setenv("R2_IMAGES_PUBLIC_URL", "https://cdn.example.com")
    monkeypatch.setattr(r2, "delete_image_url", fake_delete_url)

    async def run():
        conn = await db.get_db()
        await conn.execute(
            "INSERT INTO corpus_images (guild_id, url) VALUES (111, 'https://cdn.example.com/111/meme.png')"
        )
        await db.record_uploaded_image(111, "https://cdn.example.com/111/panel.png")
        await db.record_uploaded_image(222, "https://cdn.example.com/222/otro.png")
        await conn.execute(
            "INSERT INTO guild_departures (guild_id, left_at) "
            "VALUES (111, to_char(timezone('utc', now()) + interval '-40 days', 'YYYY-MM-DD HH24:MI:SS'))"
        )
        await conn.commit()

        cog = General(bot=_FakeBot())
        await cog.guild_cleanup_task.coro(cog)

        async with conn.execute("SELECT guild_id FROM embed_uploaded_images") as cur:
            return [r[0] for r in await cur.fetchall()]

    quedan = asyncio.run(run())

    assert sorted(borradas) == [
        "https://cdn.example.com/111/meme.png",
        "https://cdn.example.com/111/panel.png",
    ]
    assert quedan == [222]  # el otro guild no se toca

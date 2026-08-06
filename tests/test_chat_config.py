"""Tests de la configuración de chat por servidor (esquema + migración + API).

Lo que se cubre acá es lo que rompe producción en silencio:

- la migración que rellena corpus_allowed_channels (sin ella los servidores
  activos dejan de aprender de golpe el día del deploy),
- que corra una sola vez y no pise lo que un admin ya configuró,
- que los ajustes numéricos se recorten a su rango antes de llegar a la DB.

El comportamiento de on_message vive en test_chat_muted.py.
"""

import asyncio
from types import SimpleNamespace

import pytest

import db
from cogs.chat import CORPUS_ALLOWLIST_MIGRATION, ensure_corpus_migrated


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


def _guild(guild_id=1, channel_ids=(10, 20, 30)):
    """Guild falso con la única superficie que usa la migración."""
    return SimpleNamespace(
        id=guild_id,
        name="PURG4TORY",
        text_channels=[SimpleNamespace(id=cid) for cid in channel_ids],
    )


# ─── Migración del corpus ────────────────────────────────────────────────────


def test_migracion_habilita_los_canales_actuales(temp_db):
    """Un servidor que ya existía queda aprendiendo de lo mismo que antes."""

    async def run():
        seeded = await ensure_corpus_migrated(_guild())
        return seeded, await db.list_corpus_channels(1)

    seeded, allowed = asyncio.run(run())
    assert seeded == 3
    assert allowed == [10, 20, 30]


def test_migracion_excluye_los_canales_ignorados(temp_db):
    async def run():
        await db.add_ignored_channel(1, 20)
        await ensure_corpus_migrated(_guild())
        return await db.list_corpus_channels(1)

    assert asyncio.run(run()) == [10, 30]


def test_migracion_incluye_canales_sin_mensajes_guardados(temp_db):
    """Se recorren los canales reales del guild, no los que ya tienen corpus:
    un canal vacío igual tiene que quedar habilitado."""

    async def run():
        await ensure_corpus_migrated(_guild(channel_ids=(77,)))
        return await db.list_corpus_channels(1)

    assert asyncio.run(run()) == [77]


def test_migracion_no_pisa_lo_que_un_admin_ya_ajusto(temp_db):
    """Segunda corrida (reinicio del bot): no vuelve a sembrar."""

    async def run():
        await ensure_corpus_migrated(_guild())
        # El admin deja solo un canal desde el dashboard.
        await db.remove_corpus_channel(1, 20)
        await db.remove_corpus_channel(1, 30)
        segunda = await ensure_corpus_migrated(_guild())
        return segunda, await db.list_corpus_channels(1)

    segunda, allowed = asyncio.run(run())
    assert segunda is None, "la migración volvió a correr"
    assert allowed == [10], "la migración pisó la configuración del admin"


def test_migracion_es_por_servidor(temp_db):
    async def run():
        await ensure_corpus_migrated(_guild(guild_id=1, channel_ids=(10,)))
        await ensure_corpus_migrated(_guild(guild_id=2, channel_ids=(99,)))
        return await db.list_corpus_channels(1), await db.list_corpus_channels(2)

    uno, dos = asyncio.run(run())
    assert uno == [10]
    assert dos == [99]


def test_el_flag_se_marca_antes_de_sembrar(temp_db):
    """Si el seed explota, la migración NO se reintenta sola: quedaría
    pisando la configuración del admin en cada reinicio."""

    class GuildRoto:
        id = 1
        name = "roto"

        @property
        def text_channels(self):
            raise RuntimeError("Discord caído")

    async def run():
        seeded = await ensure_corpus_migrated(GuildRoto())
        return seeded, await db.migration_applied(1, CORPUS_ALLOWLIST_MIGRATION)

    seeded, applied = asyncio.run(run())
    assert seeded == 0
    assert applied is True


# ─── Allowlist del corpus ────────────────────────────────────────────────────


def test_lista_vacia_no_aprende_de_nada(temp_db):
    """El default nuevo: sin canales habilitados, nada entra al corpus."""
    assert asyncio.run(db.is_corpus_allowed(1, 10)) is False


def test_agregar_y_quitar_canal_del_corpus(temp_db):
    async def run():
        await db.add_corpus_channel(1, 10)
        dentro = await db.is_corpus_allowed(1, 10)
        await db.remove_corpus_channel(1, 10)
        return dentro, await db.is_corpus_allowed(1, 10)

    dentro, fuera = asyncio.run(run())
    assert dentro is True and fuera is False


# ─── Roles exentos del límite de menciones ───────────────────────────────────


def test_roles_exentos_se_guardan_por_servidor(temp_db):
    async def run():
        await db.add_exempt_role(1, 555)
        await db.add_exempt_role(2, 666)
        return await db.list_exempt_roles(1), await db.list_exempt_roles(2)

    uno, dos = asyncio.run(run())
    assert uno == [555]
    assert dos == [666]


# ─── Ajustes numéricos ───────────────────────────────────────────────────────


def test_defaults_replican_la_conducta_anterior(temp_db):
    """Un servidor sin fila en settings se comporta igual que con las
    constantes fijas de config.py."""
    s = asyncio.run(db.get_chat_settings(1))
    assert s["auto_generate_every"] == 15
    assert s["auto_generate_probability"] == 0.6
    assert s["reaction_probability"] == 0.05
    assert s["gif_response_probability"] == 0.45


def test_set_chat_tunables_guarda_solo_lo_enviado(temp_db):
    """El dashboard autoguarda campo por campo: mandar uno no puede resetear
    los otros a su default."""

    async def run():
        await db.set_chat_tunables(1, {"auto_generate_every": 40})
        await db.set_chat_tunables(1, {"reaction_probability": 0.2})
        return await db.get_chat_settings(1)

    s = asyncio.run(run())
    assert s["auto_generate_every"] == 40
    assert s["reaction_probability"] == 0.2
    assert s["gif_response_probability"] == 0.45  # intacto


def test_los_valores_se_recortan_al_rango(temp_db):
    async def run():
        return await db.set_chat_tunables(
            1,
            {
                "auto_generate_probability": 5.0,  # > 1
                "reaction_probability": -3,  # < 0
                "auto_generate_every": 0,  # < 1: dejaría al bot mudo
                "mention_rate_limit": 99999,
            },
        )

    saved = asyncio.run(run())
    assert saved["auto_generate_probability"] == 1.0
    assert saved["reaction_probability"] == 0.0
    assert saved["auto_generate_every"] == 1
    assert saved["mention_rate_limit"] == db.MAX_MENTION_RATE_LIMIT


def test_valores_basura_se_ignoran_sin_romper(temp_db):
    async def run():
        await db.set_chat_tunables(1, {"auto_generate_every": 30})
        await db.set_chat_tunables(1, {"auto_generate_every": "no soy un número"})
        return await db.get_chat_settings(1)

    assert asyncio.run(run())["auto_generate_every"] == 30


# ─── Migración: chat_channels -> spontaneous_channels + mention_channels ────


async def _seed_chat_channels_and_init(tmp_path, rows):
    """Simula un servidor con chat_channels ya poblada, antes de que exista
    el split: crea esa tabla a mano, la llena, y recién ahí corre init_db
    (que la copia a las dos tablas nuevas la primera vez que ve el flag)."""
    pre = await db.aiosqlite.connect(str(tmp_path / "test.db"))
    await pre.execute(
        "CREATE TABLE chat_channels (guild_id INTEGER NOT NULL, "
        "channel_id INTEGER NOT NULL, PRIMARY KEY (guild_id, channel_id))"
    )
    await pre.executemany(
        "INSERT INTO chat_channels (guild_id, channel_id) VALUES (?, ?)", rows
    )
    await pre.commit()
    await pre.close()
    await db.init_db()


def test_chat_channels_existente_se_copia_a_las_dos_listas_nuevas(
    tmp_path, monkeypatch
):
    """Un servidor ya configurado no pierde sus canales el día del deploy:
    lo que tenía queda en las dos allowlists nuevas, no en una sola."""
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)

    async def run():
        await _seed_chat_channels_and_init(tmp_path, [(1, 10), (1, 20)])
        return await db.list_spontaneous_channels(1), await db.list_mention_channels(1)

    try:
        spontaneous, mention = asyncio.run(run())
    finally:
        asyncio.run(db.close_db())
    assert spontaneous == [10, 20]
    assert mention == [10, 20]


def test_split_no_resucita_canales_que_un_admin_ya_sacó(tmp_path, monkeypatch):
    """La copia es de una sola vez (flag en disco): si un admin saca un canal
    de una lista nueva, un reinicio no debe traerlo de vuelta desde la vieja
    chat_channels, que sigue intacta."""
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)

    async def run():
        await _seed_chat_channels_and_init(tmp_path, [(1, 10), (1, 20)])
        await db.remove_spontaneous_channel(1, 20)
        # Reinicio: la migración ya corrió (flag en disco), no debe repetirse.
        await db.close_db()
        monkeypatch.setattr(db, "_db", None)
        await db.init_db()
        return await db.list_spontaneous_channels(1)

    try:
        spontaneous = asyncio.run(run())
    finally:
        asyncio.run(db.close_db())
    assert spontaneous == [10]


def test_purge_guild_data_borra_las_tablas_nuevas(temp_db):
    async def run():
        await db.add_corpus_channel(7, 10)
        await db.add_exempt_role(7, 555)
        await db.add_spontaneous_channel(7, 10)
        await db.add_mention_channel(7, 10)
        await ensure_corpus_migrated(_guild(guild_id=7))
        await db.purge_guild_data(7)
        return (
            await db.list_corpus_channels(7),
            await db.list_exempt_roles(7),
            await db.list_spontaneous_channels(7),
            await db.list_mention_channels(7),
            await db.migration_applied(7, CORPUS_ALLOWLIST_MIGRATION),
        )

    corpus, roles, spontaneous, mention, migrated = asyncio.run(run())
    assert corpus == [] and roles == [] and spontaneous == [] and mention == []
    # Sin el flag, si el bot vuelve a entrar arranca de cero como servidor nuevo.
    assert migrated is False


# ─── Overrides por canal (channel_settings) ──────────────────────────────────


def test_sin_override_el_efectivo_es_igual_al_del_servidor(temp_db):
    async def run():
        await db.set_chat_tunables(1, {"reaction_probability": 0.3})
        return await db.get_chat_settings(1), await db.get_effective_chat_settings(
            1, 10
        )

    server, effective = asyncio.run(run())
    for key in db.CHAT_TUNABLES:
        assert effective[key] == server[key]


def test_get_channel_tunables_sin_fila_devuelve_todo_none(temp_db):
    overrides = asyncio.run(db.get_channel_tunables(1, 10))
    assert overrides == dict.fromkeys(db.CHAT_TUNABLES)


def test_set_channel_tunables_guarda_solo_lo_enviado(temp_db):
    async def run():
        await db.set_channel_tunables(1, 10, {"reaction_probability": 0.9})
        return await db.get_channel_tunables(1, 10)

    overrides = asyncio.run(run())
    assert overrides["reaction_probability"] == 0.9
    # El resto sigue sin override: cae al default del servidor.
    assert overrides["auto_generate_every"] is None
    assert overrides["gif_response_probability"] is None


def test_override_de_canal_pisa_el_default_solo_en_ese_canal(temp_db):
    async def run():
        await db.set_chat_tunables(1, {"reaction_probability": 0.05})
        await db.set_channel_tunables(1, 10, {"reaction_probability": 0.9})
        return (
            await db.get_effective_chat_settings(1, 10),  # con override
            await db.get_effective_chat_settings(1, 20),  # sin override
        )

    con_override, sin_override = asyncio.run(run())
    assert con_override["reaction_probability"] == 0.9
    assert sin_override["reaction_probability"] == 0.05


def test_override_parcial_no_afecta_los_otros_tunables(temp_db):
    """Un override de un solo campo no tiene que arrastrar el resto al
    default -- cada tunable resuelve el suyo de forma independiente."""

    async def run():
        await db.set_chat_tunables(1, {"gif_response_probability": 0.2})
        await db.set_channel_tunables(1, 10, {"reaction_probability": 0.9})
        return await db.get_effective_chat_settings(1, 10)

    effective = asyncio.run(run())
    assert effective["reaction_probability"] == 0.9  # override
    assert effective["gif_response_probability"] == 0.2  # default del servidor


def test_valor_null_borra_el_override_y_vuelve_a_heredar(temp_db):
    async def run():
        await db.set_channel_tunables(1, 10, {"reaction_probability": 0.9})
        await db.set_channel_tunables(1, 10, {"reaction_probability": None})
        return (
            await db.get_channel_tunables(1, 10),
            await db.get_effective_chat_settings(1, 10),
        )

    overrides, effective = asyncio.run(run())
    assert overrides["reaction_probability"] is None
    assert effective["reaction_probability"] == db.DEFAULT_REACTION_PROBABILITY


def test_channel_tunables_se_recortan_al_mismo_rango_que_el_servidor(temp_db):
    saved = asyncio.run(
        db.set_channel_tunables(
            1,
            10,
            {
                "auto_generate_probability": 5.0,
                "reaction_probability": -3,
                "auto_generate_every": 0,
                "mention_rate_limit": 99999,
            },
        )
    )
    assert saved["auto_generate_probability"] == 1.0
    assert saved["reaction_probability"] == 0.0
    assert saved["auto_generate_every"] == 1
    assert saved["mention_rate_limit"] == db.MAX_MENTION_RATE_LIMIT


def test_overrides_no_se_mezclan_entre_canales(temp_db):
    async def run():
        await db.set_channel_tunables(1, 10, {"reaction_probability": 0.9})
        await db.set_channel_tunables(1, 20, {"reaction_probability": 0.1})
        return (
            await db.get_channel_tunables(1, 10),
            await db.get_channel_tunables(1, 20),
        )

    diez, veinte = asyncio.run(run())
    assert diez["reaction_probability"] == 0.9
    assert veinte["reaction_probability"] == 0.1


def test_overrides_no_se_mezclan_entre_guilds(temp_db):
    async def run():
        await db.set_channel_tunables(1, 10, {"reaction_probability": 0.9})
        await db.set_channel_tunables(2, 10, {"reaction_probability": 0.1})
        return (
            await db.get_channel_tunables(1, 10),
            await db.get_channel_tunables(2, 10),
        )

    uno, dos = asyncio.run(run())
    assert uno["reaction_probability"] == 0.9
    assert dos["reaction_probability"] == 0.1


def test_purge_guild_data_borra_channel_settings(temp_db):
    async def run():
        await db.set_channel_tunables(7, 10, {"reaction_probability": 0.9})
        await db.purge_guild_data(7)
        return await db.get_channel_tunables(7, 10)

    assert asyncio.run(run()) == dict.fromkeys(db.CHAT_TUNABLES)

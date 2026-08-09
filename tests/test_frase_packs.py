"""Tests de la Fase 3: canales permitidos para frases especiales + packs.

Cubre lo que puede romperse en silencio: la semántica de "sin pack" (NULL)
tiene que seguir devolviendo el pool de siempre para servidores que nunca
tocan packs, borrar un pack no puede borrar contenido, y los límites nuevos
(frases, packs) tienen que recortar igual que embed_template_limit.
"""

import asyncio

import pytest

import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


# ─── Canales permitidos para frases (frase_allowed_channels) ────────────────


def test_lista_vacia_permite_en_cualquier_canal(temp_db):
    """A diferencia de corpus_allowed_channels: acá vacía = todos permitidos."""
    assert asyncio.run(db.is_frase_allowed(1, 10)) is True


def test_agregar_un_canal_restringe_a_ese_canal(temp_db):
    async def run():
        await db.add_frase_channel(1, 10)
        return (
            await db.is_frase_allowed(1, 10),
            await db.is_frase_allowed(1, 20),
        )

    dentro, fuera = asyncio.run(run())
    assert dentro is True
    assert fuera is False


def test_quitar_el_ultimo_canal_vuelve_a_permitir_todos(temp_db):
    async def run():
        await db.add_frase_channel(1, 10)
        await db.remove_frase_channel(1, 10)
        return await db.is_frase_allowed(1, 999)

    assert asyncio.run(run()) is True


# ─── Packs: CRUD básico ──────────────────────────────────────────────────────


def test_crear_pack_y_listarlo(temp_db):
    async def run():
        pack_id = await db.add_frase_pack(1, "Navidad")
        return pack_id, await db.list_frase_packs(1)

    pack_id, packs = asyncio.run(run())
    assert pack_id is not None
    assert len(packs) == 1
    assert packs[0]["id"] == pack_id
    assert packs[0]["name"] == "Navidad"
    assert packs[0]["created_at"]


def test_nombre_vacio_no_crea_pack(temp_db):
    assert asyncio.run(db.add_frase_pack(1, "   ")) is None


def test_nombre_duplicado_en_el_mismo_guild_se_rechaza(temp_db):
    async def run():
        primero = await db.add_frase_pack(1, "Navidad")
        segundo = await db.add_frase_pack(1, "Navidad")
        return primero, segundo

    primero, segundo = asyncio.run(run())
    assert primero is not None
    assert segundo is None


def test_mismo_nombre_en_guilds_distintos_no_choca(temp_db):
    async def run():
        uno = await db.add_frase_pack(1, "Navidad")
        dos = await db.add_frase_pack(2, "Navidad")
        return uno, dos

    uno, dos = asyncio.run(run())
    assert uno is not None
    assert dos is not None


def test_packs_se_recortan_al_limite(temp_db, monkeypatch):
    monkeypatch.setenv("MAX_FRASE_PACKS_PER_GUILD_FREE", "2")

    async def run():
        a = await db.add_frase_pack(1, "A")
        b = await db.add_frase_pack(1, "B")
        c = await db.add_frase_pack(1, "C")
        return a, b, c

    a, b, c = asyncio.run(run())
    assert a is not None and b is not None
    assert c is None


def test_borrar_pack_no_borra_las_frases_vuelven_al_default(temp_db):
    async def run():
        pack_id = await db.add_frase_pack(1, "Navidad")
        await db.add_frase_especial(1, 42, "user", "feliz navidad", pack_id=pack_id)
        await db.delete_frase_pack(1, pack_id)
        frases = await db.list_frases_especiales(1)
        return frases

    frases = asyncio.run(run())
    assert len(frases) == 1
    assert frases[0]["pack_id"] is None


def test_borrar_pack_libera_los_canales_que_lo_usaban(temp_db):
    async def run():
        pack_id = await db.add_frase_pack(1, "Navidad")
        await db.assign_pack_to_channel(1, 10, pack_id)
        await db.delete_frase_pack(1, pack_id)
        return await db.get_effective_frase_pool(1, 10)

    assert asyncio.run(run()) is None


def test_borrar_pack_inexistente_devuelve_false(temp_db):
    assert asyncio.run(db.delete_frase_pack(1, 999)) is False


# ─── Asignación de pack a canal ──────────────────────────────────────────────


def test_canal_sin_pack_asignado_usa_el_pool_default(temp_db):
    assert asyncio.run(db.get_effective_frase_pool(1, 10)) is None


def test_asignar_un_pack_a_un_canal(temp_db):
    async def run():
        pack_id = await db.add_frase_pack(1, "Navidad")
        await db.assign_pack_to_channel(1, 10, pack_id)
        return pack_id, await db.get_effective_frase_pool(1, 10)

    pack_id, effective = asyncio.run(run())
    assert effective == pack_id


def test_asignar_un_pack_nuevo_reemplaza_al_anterior(temp_db):
    async def run():
        a = await db.add_frase_pack(1, "A")
        b = await db.add_frase_pack(1, "B")
        await db.assign_pack_to_channel(1, 10, a)
        await db.assign_pack_to_channel(1, 10, b)
        return b, await db.get_effective_frase_pool(1, 10)

    b, effective = asyncio.run(run())
    assert effective == b


def test_un_pack_puede_asignarse_a_varios_canales(temp_db):
    async def run():
        pack_id = await db.add_frase_pack(1, "Navidad")
        await db.assign_pack_to_channel(1, 10, pack_id)
        await db.assign_pack_to_channel(1, 20, pack_id)
        return pack_id, await db.list_pack_channels(1, pack_id)

    pack_id, channels = asyncio.run(run())
    assert channels == [10, 20]


def test_unassign_exige_el_pack_id_esperado(temp_db):
    """Un pack_id viejo en la URL no debe poder borrar una reasignación más
    nueva a otro pack."""

    async def run():
        a = await db.add_frase_pack(1, "A")
        b = await db.add_frase_pack(1, "B")
        await db.assign_pack_to_channel(1, 10, a)
        await db.assign_pack_to_channel(1, 10, b)  # reasignado a B
        removed_con_a_viejo = await db.unassign_pack_from_channel(1, 10, a)
        return removed_con_a_viejo, await db.get_effective_frase_pool(1, 10)

    removed, effective = asyncio.run(run())
    assert removed is False
    assert effective is not None  # sigue apuntando a B, no se tocó


# ─── Sección 6, ronda 1: pack_id es un autoincrement global, no scopeado por
# guild -- assign_pack_to_channel/set_frase_pack tienen que validar que el
# pack pertenezca al guild que lo usa, o un guild podría apuntar su propio
# canal/frase al pack_id de OTRO guild (adivinable/enumerable, autoincrement
# secuencial). Hoy ningún query de lectura junta contenido ajeno a través de
# eso (get_random_frase_especial siempre filtra por guild_id Y pack_id
# juntos), pero es la validación que faltaba para que siga siendo así aunque
# algo nuevo se apoye en pack_id solo.


def test_asignar_pack_de_otro_guild_a_un_canal_se_rechaza(temp_db):
    async def run():
        guild_a, guild_b = 1, 2
        ajeno = await db.add_frase_pack(guild_b, "Pack de B")
        ok = await db.assign_pack_to_channel(guild_a, 10, ajeno)
        return ok, await db.get_effective_frase_pool(guild_a, 10)

    ok, effective = asyncio.run(run())
    assert ok is False
    assert effective is None  # el canal de A no quedó apuntando al pack de B


def test_asignar_pack_propio_sigue_funcionando_tras_la_validacion(temp_db):
    """La validación nueva no debe romper el caso normal (mismo guild)."""

    async def run():
        pack_id = await db.add_frase_pack(1, "Navidad")
        ok = await db.assign_pack_to_channel(1, 10, pack_id)
        return ok, await db.get_effective_frase_pool(1, 10)

    ok, effective = asyncio.run(run())
    assert ok is True
    assert effective is not None


def test_reasignar_frase_a_pack_de_otro_guild_se_rechaza(temp_db):
    async def run():
        guild_a, guild_b = 1, 2
        await db.add_frase_especial(guild_a, 5, "user", "hola")
        frase_id = (await db.list_frases_especiales(guild_a))[0]["id"]
        ajeno = await db.add_frase_pack(guild_b, "Pack de B")
        updated = await db.set_frase_pack(guild_a, frase_id, ajeno)
        frases = await db.list_frases_especiales(guild_a)
        return updated, frases[0]["pack_id"]

    updated, pack_id_after = asyncio.run(run())
    assert updated is False
    assert pack_id_after is None  # no quedó apuntando al pack ajeno


def test_unassign_con_el_pack_correcto_libera_el_canal(temp_db):
    async def run():
        pack_id = await db.add_frase_pack(1, "Navidad")
        await db.assign_pack_to_channel(1, 10, pack_id)
        removed = await db.unassign_pack_from_channel(1, 10, pack_id)
        return removed, await db.get_effective_frase_pool(1, 10)

    removed, effective = asyncio.run(run())
    assert removed is True
    assert effective is None


# ─── get_random_frase_especial respeta el pool efectivo ─────────────────────


def test_pool_default_no_incluye_frases_de_un_pack(temp_db):
    async def run():
        pack_id = await db.add_frase_pack(1, "Navidad")
        await db.add_frase_especial(1, 1, "u", "frase de navidad", pack_id=pack_id)
        await db.add_frase_especial(1, 1, "u", "frase default")
        elegidas = {await db.get_random_frase_especial(1, None) for _ in range(20)}
        return elegidas

    elegidas = asyncio.run(run())
    assert elegidas == {"frase default"}


def test_pool_de_un_pack_no_incluye_frases_default(temp_db):
    async def run():
        pack_id = await db.add_frase_pack(1, "Navidad")
        await db.add_frase_especial(1, 1, "u", "frase de navidad", pack_id=pack_id)
        await db.add_frase_especial(1, 1, "u", "frase default")
        elegidas = {await db.get_random_frase_especial(1, pack_id) for _ in range(20)}
        return elegidas

    elegidas = asyncio.run(run())
    assert elegidas == {"frase de navidad"}


def test_reasignar_el_pack_de_una_frase_existente(temp_db):
    async def run():
        pack_id = await db.add_frase_pack(1, "Navidad")
        await db.add_frase_especial(1, 1, "u", "frase suelta")
        frase_id = (await db.list_frases_especiales(1))[0]["id"]
        updated = await db.set_frase_pack(1, frase_id, pack_id)
        frase = await db.get_frase_especial(1, frase_id)
        return updated, frase["pack_id"]

    updated, pack_id_guardado = asyncio.run(run())
    assert updated is True
    assert pack_id_guardado is not None


# ─── Límite de frases ────────────────────────────────────────────────────────


def test_frases_se_recortan_al_limite(temp_db, monkeypatch):
    monkeypatch.setenv("MAX_FRASES_PER_GUILD_FREE", "2")

    async def run():
        a = await db.add_frase_especial(1, 1, "u", "una")
        b = await db.add_frase_especial(1, 1, "u", "dos")
        c = await db.add_frase_especial(1, 1, "u", "tres")
        return a, b, c

    a, b, c = asyncio.run(run())
    assert a is True and b is True
    assert c is None


def test_texto_vacio_devuelve_false_no_none(temp_db):
    """False (vacío) y None (límite) son casos distintos -- no hay que
    confundirlos aunque los dos sean 'no se guardó'."""
    assert asyncio.run(db.add_frase_especial(1, 1, "u", "   ")) is False


# ─── purge_guild_data ────────────────────────────────────────────────────────


def test_purge_guild_data_borra_las_tablas_de_frases(temp_db):
    async def run():
        pack_id = await db.add_frase_pack(7, "Navidad")
        await db.add_frase_channel(7, 10)
        await db.assign_pack_to_channel(7, 10, pack_id)
        await db.add_frase_especial(7, 1, "u", "frase", pack_id=pack_id)
        await db.purge_guild_data(7)
        return (
            await db.list_frase_packs(7),
            await db.list_frase_channels(7),
            await db.list_frases_especiales(7),
            await db.get_effective_frase_pool(7, 10),
        )

    packs, channels, frases, pool = asyncio.run(run())
    assert packs == [] and channels == [] and frases == []
    assert pool is None

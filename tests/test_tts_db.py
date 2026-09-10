"""Tests para la persistencia en base de datos de TTS (tts_user_settings, tts_guild_settings)."""

import asyncio

import aiosqlite
import pytest

import db
from db import (
    delete_user_data,
    get_tts_guild_settings,
    get_tts_user_settings,
    purge_guild_data,
    set_tts_guild_settings,
    set_tts_user_settings,
)


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


def test_tts_user_settings_crud(memory_db):
    async def _test():
        user_id = 987654321

        # Inicialmente None
        assert await get_tts_user_settings(user_id) is None

        # Insertar settings completos
        saved = await set_tts_user_settings(
            user_id=user_id,
            voice_id="es_female_f6",
            filter_name="nightcore",
            speed=1.2,
            pitch=1.1,
        )
        assert saved["user_id"] == user_id
        assert saved["voice_id"] == "es_female_f6"
        assert saved["filter"] == "nightcore"
        assert saved["speed"] == 1.2
        assert saved["pitch"] == 1.1

        # Consultar y verificar persistencia
        fetched = await get_tts_user_settings(user_id)
        assert fetched is not None
        assert fetched["voice_id"] == "es_female_f6"
        assert fetched["filter"] == "nightcore"
        assert fetched["speed"] == 1.2
        assert fetched["pitch"] == 1.1

        # Actualización parcial (solo voz)
        updated = await set_tts_user_settings(user_id=user_id, voice_id="es_male_m3")
        assert updated["voice_id"] == "es_male_m3"
        assert updated["filter"] == "nightcore"  # Conserva
        assert updated["speed"] == 1.2  # Conserva

        # Actualización parcial (solo filtro y velocidad)
        updated2 = await set_tts_user_settings(
            user_id=user_id, filter_name="vaporwave", speed=0.8
        )
        assert updated2["voice_id"] == "es_male_m3"
        assert updated2["filter"] == "vaporwave"
        assert updated2["speed"] == 0.8

        # delete_user_data limpia la fila de tts_user_settings
        await delete_user_data(user_id)
        assert await get_tts_user_settings(user_id) is None

    asyncio.run(_test())


def test_tts_guild_settings_crud(memory_db):
    async def _test():
        guild_id = 123456789

        # Inicialmente None
        assert await get_tts_guild_settings(guild_id) is None

        # Guardar voz por defecto del servidor
        saved = await set_tts_guild_settings(guild_id=guild_id, default_voice="es_002")
        assert saved["guild_id"] == guild_id
        assert saved["default_voice"] == "es_002"

        # Consultar
        fetched = await get_tts_guild_settings(guild_id)
        assert fetched is not None
        assert fetched["default_voice"] == "es_002"

        # Actualizar
        updated = await set_tts_guild_settings(
            guild_id=guild_id, default_voice="es-ES-AlvaroNeural"
        )
        assert updated["default_voice"] == "es-ES-AlvaroNeural"

        # Aislamiento entre guilds
        other_guild = 999
        assert await get_tts_guild_settings(other_guild) is None

        # purge_guild_data limpia tts_guild_settings
        await purge_guild_data(guild_id)
        assert await get_tts_guild_settings(guild_id) is None

    asyncio.run(_test())

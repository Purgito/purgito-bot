import asyncio
import aiosqlite
import pytest
import db


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


def test_list_audit_log_filters_and_search(memory_db):
    async def run():
        guild_id = 12345
        other_guild = 67890

        # Poblamos registros de auditoría
        await db.log_audit(
            guild_id, 101, "Frambuesa", "frases.add", "frase especial de bienvenida"
        )
        await db.log_audit(
            guild_id, 101, "Frambuesa", "frases.edit", "frase editada de despedida"
        )
        await db.log_audit(
            guild_id,
            102,
            "Ana",
            "gifs.add",
            "https://media.giphy.com/media/test/giphy.gif",
        )
        await db.log_audit(
            guild_id, 102, "Ana", "gifs.block", "https://tenor.com/view/bad-gif"
        )
        await db.log_audit(guild_id, 103, "Carlos", "chat.settings_update", "chance=25")
        await db.log_audit(
            guild_id, 103, "Carlos", "youtube.add", "Canal de Tutoriales"
        )
        await db.log_audit(
            other_guild, 999, "Intruso", "frases.add", "frase otro server"
        )

        # 1. Sin filtros: trae los 6 del guild ordenados por id DESC
        entries, has_more = await db.list_audit_log_page(guild_id, limit=10)
        assert len(entries) == 6
        assert not has_more
        assert not any(e["user_name"] == "Intruso" for e in entries)

        # 2. Búsqueda por texto (q)
        entries, _ = await db.list_audit_log_page(guild_id, q="bienvenida")
        assert len(entries) == 1
        assert entries[0]["action"] == "frases.add"

        # Búsqueda insensible a mayúsculas/minúsculas
        entries, _ = await db.list_audit_log_page(guild_id, q="BIENVENIDA")
        assert len(entries) == 1

        # Búsqueda por nombre de usuario
        entries, _ = await db.list_audit_log_page(guild_id, q="Frambuesa")
        assert len(entries) == 2

        # 3. Filtro por user_id
        entries, _ = await db.list_audit_log_page(guild_id, user_id=102)
        assert len(entries) == 2
        assert {e["action"] for e in entries} == {"gifs.add", "gifs.block"}

        # 4. Filtro por acción puntual
        entries, _ = await db.list_audit_log_page(guild_id, action="gifs.block")
        assert len(entries) == 1
        assert entries[0]["detail"] == "https://tenor.com/view/bad-gif"

        # 5. Filtro por prefijo de acción
        entries, _ = await db.list_audit_log_page(guild_id, action="frases.")
        assert len(entries) == 2

        # 6. Filtro por categoría
        entries, _ = await db.list_audit_log_page(guild_id, action="cat:multimedia")
        assert len(entries) == 2
        assert all(e["action"].startswith("gifs.") for e in entries)

        entries, _ = await db.list_audit_log_page(guild_id, action="cat:contenido")
        assert len(entries) == 2
        assert all(e["action"].startswith("frases.") for e in entries)

        # 7. Combinación de filtros (usuario + búsqueda)
        entries, _ = await db.list_audit_log_page(guild_id, user_id=101, q="editada")
        assert len(entries) == 1
        assert entries[0]["action"] == "frases.edit"

        # 8. Filtro sin coincidencias
        entries, has_more = await db.list_audit_log_page(
            guild_id, q="texto_inexistente_123"
        )
        assert len(entries) == 0
        assert not has_more

    asyncio.run(run())


def test_audit_log_pagination_with_cursor_and_filters(memory_db):
    async def run():
        guild_id = 12345

        # Insertamos 15 entradas de frases
        for i in range(1, 16):
            await db.log_audit(
                guild_id, 101, "Frambuesa", "frases.add", f"frase #{i:02d}"
            )

        # Página 1 (5 items)
        page1, has_more1 = await db.list_audit_log_page(
            guild_id, limit=5, action="frases."
        )
        assert len(page1) == 5
        assert has_more1 is True
        assert page1[0]["detail"] == "frase #15"
        assert page1[4]["detail"] == "frase #11"

        # Página 2 usando cursor before_id
        cursor1 = page1[-1]["id"]
        page2, has_more2 = await db.list_audit_log_page(
            guild_id, before_id=cursor1, limit=5, action="frases."
        )
        assert len(page2) == 5
        assert has_more2 is True
        assert page2[0]["detail"] == "frase #10"
        assert page2[4]["detail"] == "frase #06"

        # Página 3
        cursor2 = page2[-1]["id"]
        page3, has_more3 = await db.list_audit_log_page(
            guild_id, before_id=cursor2, limit=5, action="frases."
        )
        assert len(page3) == 5
        assert has_more3 is False
        assert page3[0]["detail"] == "frase #05"
        assert page3[4]["detail"] == "frase #01"

    asyncio.run(run())


def test_get_audit_log_users_distinct_and_isolated(memory_db):
    async def run():
        guild_id = 12345
        other_guild = 67890

        await db.log_audit(guild_id, 101, "Zoe", "frases.add", "test")
        await db.log_audit(guild_id, 102, "Ana", "gifs.add", "test")
        await db.log_audit(guild_id, 101, "Zoe", "frases.edit", "test 2")
        await db.log_audit(other_guild, 999, "Otro", "frases.add", "test")

        users = await db.get_audit_log_users(guild_id)
        assert len(users) == 2
        assert users[0] == {"user_id": 102, "user_name": "Ana"}
        assert users[1] == {"user_id": 101, "user_name": "Zoe"}

    asyncio.run(run())


def test_audit_log_user_id_snowflake_isolation(memory_db):
    """Verifica que el filtro por user_id use el snowflake real de 64 bits y no filtre eventos de otros usuarios ni de otros guilds."""

    async def run():
        guild_a = 111111111111111111
        guild_b = 222222222222222222

        frambuesa_id = 1471724794411089920
        ana_id = 1471724794411089921

        # Guild A:
        # Evento 1: Frambuesa
        # Evento 2: Ana
        # Evento 3: Frambuesa
        await db.log_audit(guild_a, frambuesa_id, "Frambuesa", "frases.add", "evento 1")
        await db.log_audit(guild_a, ana_id, "Ana", "gifs.add", "evento 2")
        await db.log_audit(
            guild_a, frambuesa_id, "Frambuesa", "chat.settings_update", "evento 3"
        )

        # Guild B:
        # Evento 4: Frambuesa
        await db.log_audit(guild_b, frambuesa_id, "Frambuesa", "frases.add", "evento 4")

        # Consulta en Guild A filtrando por Frambuesa (tanto int como str)
        entries_int, _ = await db.list_audit_log_page(guild_a, user_id=frambuesa_id)
        assert len(entries_int) == 2
        assert entries_int[0]["detail"] == "evento 3"
        assert entries_int[1]["detail"] == "evento 1"
        assert all(e["user_id"] == frambuesa_id for e in entries_int)
        assert not any(e["detail"] in ("evento 2", "evento 4") for e in entries_int)

        entries_str, _ = await db.list_audit_log_page(
            guild_a, user_id=str(frambuesa_id)
        )
        assert len(entries_str) == 2
        assert entries_str[0]["detail"] == "evento 3"
        assert entries_str[1]["detail"] == "evento 1"

        # Consulta en Guild A filtrando por Ana
        entries_ana, _ = await db.list_audit_log_page(guild_a, user_id=ana_id)
        assert len(entries_ana) == 1
        assert entries_ana[0]["detail"] == "evento 2"
        assert entries_ana[0]["user_id"] == ana_id

    asyncio.run(run())


def test_audit_log_pagination_with_user_filter(memory_db):
    """Verifica que el filtro por usuario se aplique en SQL ANTES de la paginación y se mantenga en Cargar más."""

    async def run():
        guild_id = 123456789012345678
        frambuesa_id = 1471724794411089920
        ana_id = 1471724794411089921

        # Intercalamos 7 eventos de Frambuesa y 7 eventos de Ana
        for i in range(1, 8):
            await db.log_audit(
                guild_id, frambuesa_id, "Frambuesa", "frases.add", f"frambuesa #{i:02d}"
            )
            await db.log_audit(guild_id, ana_id, "Ana", "gifs.add", f"ana #{i:02d}")

        # Página 1 para Frambuesa con limit=5
        page1, has_more1 = await db.list_audit_log_page(
            guild_id, user_id=frambuesa_id, limit=5
        )
        assert len(page1) == 5
        assert has_more1 is True
        assert page1[0]["detail"] == "frambuesa #07"
        assert page1[4]["detail"] == "frambuesa #03"
        assert all(e["user_id"] == frambuesa_id for e in page1)

        # Página 2 (Cargar más) usando before_id
        cursor1 = page1[-1]["id"]
        page2, has_more2 = await db.list_audit_log_page(
            guild_id, user_id=frambuesa_id, before_id=cursor1, limit=5
        )
        assert len(page2) == 2
        assert has_more2 is False
        assert page2[0]["detail"] == "frambuesa #02"
        assert page2[1]["detail"] == "frambuesa #01"
        assert all(e["user_id"] == frambuesa_id for e in page2)

    asyncio.run(run())


def test_audit_log_combinations_all_filters(memory_db):
    """Verifica combinaciones de filtros: Usuario + Acción + Fecha + Búsqueda."""

    async def run():
        guild_id = 987654321098765432
        frambuesa_id = 1471724794411089920
        ana_id = 1471724794411089921

        await db.log_audit(
            guild_id, frambuesa_id, "Frambuesa", "frases.add", "chad meme"
        )
        await db.log_audit(
            guild_id, frambuesa_id, "Frambuesa", "frases.edit", "otra cosa"
        )
        await db.log_audit(guild_id, frambuesa_id, "Frambuesa", "gifs.add", "chad gif")
        await db.log_audit(guild_id, ana_id, "Ana", "frases.add", "chad de ana")

        # 1. Usuario
        r1, _ = await db.list_audit_log_page(guild_id, user_id=frambuesa_id)
        assert len(r1) == 3

        # 2. Usuario + Acción
        r2, _ = await db.list_audit_log_page(
            guild_id, user_id=frambuesa_id, action="frases."
        )
        assert len(r2) == 2

        # 3. Usuario + Búsqueda
        r3, _ = await db.list_audit_log_page(guild_id, user_id=frambuesa_id, q="chad")
        assert len(r3) == 2
        assert {e["action"] for e in r3} == {"frases.add", "gifs.add"}

        # 4. Usuario + Acción + Búsqueda
        r4, _ = await db.list_audit_log_page(
            guild_id, user_id=frambuesa_id, action="frases.", q="chad"
        )
        assert len(r4) == 1
        assert r4[0]["detail"] == "chad meme"

        # 5. Usuario + Fecha + Acción + Búsqueda
        r5, _ = await db.list_audit_log_page(
            guild_id,
            user_id=frambuesa_id,
            action="frases.",
            q="chad",
            date_from="2020-01-01",
            date_to="2035-01-01",
        )
        assert len(r5) == 1
        assert r5[0]["detail"] == "chad meme"

        # 6. Combinación sin coincidencia
        r6, _ = await db.list_audit_log_page(
            guild_id, user_id=frambuesa_id, q="inexistente"
        )
        assert len(r6) == 0

    asyncio.run(run())


class FakeRequest:
    def __init__(self, guild_id=12345, query=None, ip="1.2.3.4"):
        self.match_info = {"guild_id": str(guild_id)}
        self.query = query or {}
        self.headers = {"X-Forwarded-For": ip}
        self.remote = ip


def test_api_audit_log_endpoint_filters_and_users(memory_db, monkeypatch):
    import json
    import webapi
    from types import SimpleNamespace

    # Mock de autenticación para pasar @guild_api
    async def fake_get_session(request):
        return {"user_id": 101, "username": "Frambuesa"}

    async def fake_check_access(request, guild_id):
        return None

    def fake_bot_guild(request, guild_id):
        return SimpleNamespace(id=guild_id)

    monkeypatch.setattr(webapi, "get_session", fake_get_session)
    monkeypatch.setattr(webapi, "check_guild_access", fake_check_access)
    monkeypatch.setattr(webapi, "_bot_guild", fake_bot_guild)

    async def run():
        guild_id = 12345
        frambuesa_id = 1471724794411089920
        ana_id = 1471724794411089921

        await db.log_audit(guild_id, frambuesa_id, "Frambuesa", "frases.add", "frase 1")
        await db.log_audit(guild_id, ana_id, "Ana", "gifs.add", "gif 1")

        # 1. GET sin query (página inicial) -> devuelve entries, has_more y lista de users con snowflakes como string
        req = FakeRequest(guild_id=guild_id, query={})
        resp = await webapi._api_audit_log_get(req)
        data = json.loads(resp.body.decode())

        assert len(data["entries"]) == 2
        assert data["has_more"] is False
        assert len(data["users"]) == 2
        assert data["users"][0]["user_name"] == "Ana"
        assert data["users"][0]["user_id"] == str(ana_id)
        assert data["users"][1]["user_name"] == "Frambuesa"
        assert data["users"][1]["user_id"] == str(frambuesa_id)

        # 2. GET con filtro de búsqueda
        req_search = FakeRequest(guild_id=guild_id, query={"q": "gif"})
        resp_search = await webapi._api_audit_log_get(req_search)
        data_search = json.loads(resp_search.body.decode())

        assert len(data_search["entries"]) == 1
        assert data_search["entries"][0]["action"] == "gifs.add"

        # 3. GET con filtro de usuario por snowflake real
        req_user = FakeRequest(guild_id=guild_id, query={"user_id": str(frambuesa_id)})
        resp_user = await webapi._api_audit_log_get(req_user)
        data_user = json.loads(resp_user.body.decode())

        assert len(data_user["entries"]) == 1
        assert data_user["entries"][0]["user_name"] == "Frambuesa"
        assert data_user["entries"][0]["user_id"] == str(frambuesa_id)

        # 4. GET con filtro de acción por categoría
        req_cat = FakeRequest(guild_id=guild_id, query={"action": "cat:contenido"})
        resp_cat = await webapi._api_audit_log_get(req_cat)
        data_cat = json.loads(resp_cat.body.decode())
        assert len(data_cat["entries"]) == 1
        assert data_cat["entries"][0]["action"] == "frases.add"

        # 5. GET con rango de fechas
        req_date = FakeRequest(
            guild_id=guild_id,
            query={"date_from": "2020-01-01", "date_to": "2030-01-01"},
        )
        resp_date = await webapi._api_audit_log_get(req_date)
        data_date = json.loads(resp_date.body.decode())
        assert len(data_date["entries"]) == 2

    asyncio.run(run())


def test_frontend_historial_user_id_request_and_behavior():
    """Verifica que historial.js arme la query con user_id y preserve el snowflake real."""
    from pathlib import Path

    historial_js = (
        Path(__file__).parent.parent / "landing" / "js" / "tabs" / "historial.js"
    ).read_text("utf-8")

    # Verifica que fetchAudit use 'user_id'
    assert "if (state.userId) params.set('user_id', state.userId);" in historial_js

    # Verifica que el select use String(u.user_id)
    assert "el('option', { value: String(u.user_id) }, u.user_name)" in historial_js

    # Verifica que el cambio de usuario asigne state.userId y llame a reloadPage
    assert "state.userId = userSelect.value;" in historial_js
    assert "reloadPage();" in historial_js

    # Verifica que reloadPage resetee el cursor
    assert "state.cursor = null;" in historial_js

    # Verifica que el chip de usuario muestre el nombre y al quitarlo limpie state.userId
    assert "Usuario: ${name}" in historial_js
    assert "state.userId = '';" in historial_js

"""Tests del chequeo de salud de GIFs guardados (r2.check_gif_url_health +
db.record_gif_health_check): distinguir un link genuinamente muerto (404/410,
content-type inválido) de uno que el navegador no puede previsualizar por
hotlink protection pero que a Discord le sigue funcionando -- no hay que
confundir eso último con "roto" y borrarlo.

check_gif_url_health nunca debe mandar un Referer de navegador (por eso no
usa `requests.Session` con referer seteado): así se comporta parecido a como
Discord desempaqueta el link, no a un <img> de página.

record_gif_health_check solo borra tras 2 'dead' seguidos -- una caída
puntual del host (timeout aislado) no debe tirar un GIF válido.
Usa una DB SQLite en memoria inyectada en db._db, sin tocar data/bot.db.
"""

import asyncio

import aiosqlite
import pytest

import cogs.gifs as gifs_mod
import db
import r2

_GUILD = 1


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    monkeypatch.setattr(r2, "delete_url", _noop_delete_url)
    yield conn
    asyncio.run(conn.close())


async def _noop_delete_url(url):
    return None


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    return conn


async def _insert_gif(conn, guild_id, url) -> int:
    cur = await conn.execute(
        "INSERT INTO corpus_gifs (guild_id, url) VALUES (?, ?)", (guild_id, url)
    )
    await conn.commit()
    return cur.lastrowid


async def _row(conn, gif_id):
    cur = await conn.execute(
        "SELECT last_health_check, checked_at, dead_streak FROM corpus_gifs WHERE id=?",
        (gif_id,),
    )
    return await cur.fetchone()


# ---------- r2.check_gif_url_health ----------


class _FakeResp:
    def __init__(self, status_code, content_type=None):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type} if content_type else {}

    def close(self):
        pass


def test_health_ok_on_200_with_valid_content_type(monkeypatch):
    monkeypatch.setattr(
        r2.requests, "head", lambda *a, **k: _FakeResp(200, "image/gif")
    )
    assert r2.check_gif_url_health("https://example.com/x.gif") == "ok"


def test_health_dead_on_404(monkeypatch):
    monkeypatch.setattr(r2.requests, "head", lambda *a, **k: _FakeResp(404))
    assert r2.check_gif_url_health("https://example.com/gone.gif") == "dead"


def test_health_dead_on_410(monkeypatch):
    monkeypatch.setattr(r2.requests, "head", lambda *a, **k: _FakeResp(410))
    assert r2.check_gif_url_health("https://example.com/gone.gif") == "dead"


def test_health_dead_on_invalid_content_type(monkeypatch):
    # 200 pero devuelve una página HTML de error -- no es un medio válido.
    monkeypatch.setattr(
        r2.requests, "head", lambda *a, **k: _FakeResp(200, "text/html")
    )
    assert r2.check_gif_url_health("https://example.com/x.gif") == "dead"


def test_health_unreachable_on_timeout(monkeypatch):
    def raise_timeout(*a, **k):
        raise r2.requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(r2.requests, "head", raise_timeout)
    assert r2.check_gif_url_health("https://example.com/x.gif") == "unreachable"


def test_health_falls_back_to_get_when_head_unsupported(monkeypatch):
    calls = []

    def fake_head(*a, **k):
        calls.append("head")
        return _FakeResp(405)

    def fake_get(*a, **k):
        calls.append("get")
        return _FakeResp(200, "image/gif")

    monkeypatch.setattr(r2.requests, "head", fake_head)
    monkeypatch.setattr(r2.requests, "get", fake_get)
    assert r2.check_gif_url_health("https://example.com/x.gif") == "ok"
    assert calls == ["head", "get"]


def test_health_no_referer_header_sent(monkeypatch):
    """No debe mandar Referer: es justamente lo que evita que un host con
    hotlink protection lo bloquee como bloquearía a un navegador."""
    seen = {}

    def fake_head(url, headers=None, **k):
        seen["headers"] = headers or {}
        return _FakeResp(200, "image/gif")

    monkeypatch.setattr(r2.requests, "head", fake_head)
    r2.check_gif_url_health("https://example.com/x.gif")
    assert "Referer" not in seen["headers"]


# ---------- db.record_gif_health_check ----------


def test_ok_resets_streak_and_keeps_gif(memory_db):
    async def run():
        gid = await _insert_gif(memory_db, _GUILD, "https://example.com/a.gif")
        deleted = await db.record_gif_health_check(gid, "ok")
        assert deleted is False
        row = await _row(memory_db, gid)
        assert row == ("ok", row[1], 0)

    asyncio.run(run())


def test_single_dead_does_not_delete(memory_db):
    """Una sola confirmación 'dead' no alcanza -- podría ser el host caído
    30 segundos, no un link roto de verdad."""

    async def run():
        gid = await _insert_gif(memory_db, _GUILD, "https://example.com/a.gif")
        deleted = await db.record_gif_health_check(gid, "dead")
        assert deleted is False
        row = await _row(memory_db, gid)
        assert row == ("dead", row[1], 1)
        cur = await memory_db.execute(
            "SELECT COUNT(*) FROM corpus_gifs WHERE id=?", (gid,)
        )
        assert (await cur.fetchone())[0] == 1

    asyncio.run(run())


def test_two_consecutive_dead_deletes(memory_db):
    async def run():
        gid = await _insert_gif(memory_db, _GUILD, "https://example.com/a.gif")
        assert await db.record_gif_health_check(gid, "dead") is False
        assert await db.record_gif_health_check(gid, "dead") is True
        cur = await memory_db.execute(
            "SELECT COUNT(*) FROM corpus_gifs WHERE id=?", (gid,)
        )
        assert (await cur.fetchone())[0] == 0

    asyncio.run(run())


def test_unreachable_does_not_count_toward_dead_streak(memory_db):
    """dead, unreachable, dead -- el 'unreachable' del medio no debe sumar
    (ni resetear) el streak: solo dos 'dead' SEGUIDOS deben borrar."""

    async def run():
        gid = await _insert_gif(memory_db, _GUILD, "https://example.com/a.gif")
        assert await db.record_gif_health_check(gid, "dead") is False
        assert await db.record_gif_health_check(gid, "unreachable") is False
        row = await _row(memory_db, gid)
        assert row[2] == 1  # streak sigue en 1, no se resetea ni se pierde
        assert await db.record_gif_health_check(gid, "dead") is True

    asyncio.run(run())


def test_ok_after_dead_resets_streak(memory_db):
    async def run():
        gid = await _insert_gif(memory_db, _GUILD, "https://example.com/a.gif")
        assert await db.record_gif_health_check(gid, "dead") is False
        assert await db.record_gif_health_check(gid, "ok") is False
        # Vuelve a fallar una vez: no debería borrar porque el streak se reseteó.
        assert await db.record_gif_health_check(gid, "dead") is False
        row = await _row(memory_db, gid)
        assert row[2] == 1

    asyncio.run(run())


def test_get_gifs_for_health_check_prioritizes_never_checked_and_oldest(memory_db):
    async def run():
        a = await _insert_gif(memory_db, _GUILD, "https://example.com/a.gif")
        b = await _insert_gif(memory_db, _GUILD, "https://example.com/b.gif")
        c = await _insert_gif(memory_db, _GUILD, "https://example.com/c.gif")
        # b ya fue chequeado (tiene checked_at); a y c nunca.
        await db.record_gif_health_check(b, "ok")

        gifs = await db.get_gifs_for_health_check(_GUILD, limit=10)
        ids = [g["id"] for g in gifs]
        # a y c (nunca chequeados) deben ir antes que b (ya chequeado).
        assert ids.index(b) > ids.index(a)
        assert ids.index(b) > ids.index(c)

    asyncio.run(run())


# ---------- cogs.gifs.resolve_media_url ----------
#
# El oEmbed de tenor no trae "url" (solo "thumbnail_url") y el de giphy no
# trae "thumbnail_url" (solo "url"). Antes el código pedía la clave que cada
# host NO tiene -> KeyError silenciado -> media_url quedaba NULL para
# siempre -> el chequeo de salud caía al fallback gif["url"] (la página HTML
# tenor.com/view/... o giphy.com/gifs/...), que responde 200 con
# Content-Type text/html y por eso se clasificaba como "dead" SIEMPRE, sin
# importar si el gif seguía vivo. Esto fue lo que causó el auto-borrado
# masivo y correlacionado del incidente: cualquier gif de tenor/giphy
# revisado dos veces terminaba borrado, garantizado.


class _FakeOEmbedResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_resolve_media_url_tenor_uses_thumbnail_url(monkeypatch):
    async def run():
        import requests

        monkeypatch.setattr(
            requests,
            "get",
            lambda *a, **k: _FakeOEmbedResp(
                {"thumbnail_url": "https://media.tenor.com/x.png"}
            ),
        )
        result = await gifs_mod.resolve_media_url(
            "https://tenor.com/view/foo-gif-123"
        )
        assert result == "https://media.tenor.com/x.png"

    asyncio.run(run())


def test_resolve_media_url_giphy_uses_url(monkeypatch):
    async def run():
        import requests

        monkeypatch.setattr(
            requests,
            "get",
            lambda *a, **k: _FakeOEmbedResp(
                {"url": "https://media1.giphy.com/media/x/giphy.gif"}
            ),
        )
        result = await gifs_mod.resolve_media_url("https://giphy.com/gifs/foo")
        assert result == "https://media1.giphy.com/media/x/giphy.gif"

    asyncio.run(run())


# ---------- cogs.gifs.get_live_gif ----------
#
# Antes usaba r2.is_url_alive: cualquier fallo (timeout, 403, rate-limit...)
# contaba igual que un link confirmado muerto, y a la 3ra vez borraba GIFs
# que en Discord seguían andando perfecto. Ahora reusa el mismo chequeo
# tri-estado que el ciclo de salud diario: "unreachable" no cuenta como
# confirmación de nada.


def test_get_live_gif_single_unreachable_does_not_delete(memory_db, monkeypatch):
    """Un timeout puntual en el único candidato no debe borrarlo -- debe
    devolver None esta vez, no confirmar el link como muerto."""

    async def run():
        gid = await _insert_gif(memory_db, _GUILD, "https://example.com/a.gif")
        monkeypatch.setattr(r2, "check_gif_url_health", lambda *a, **k: "unreachable")

        result = await gifs_mod.get_live_gif(_GUILD, attempts=1)
        assert result is None

        cur = await memory_db.execute(
            "SELECT COUNT(*) FROM corpus_gifs WHERE id=?", (gid,)
        )
        assert (await cur.fetchone())[0] == 1  # sigue ahí

    asyncio.run(run())


def test_get_live_gif_returns_ok_candidate(memory_db, monkeypatch):
    async def run():
        await _insert_gif(memory_db, _GUILD, "https://example.com/a.gif")
        monkeypatch.setattr(r2, "check_gif_url_health", lambda *a, **k: "ok")

        result = await gifs_mod.get_live_gif(_GUILD, attempts=1)
        assert result == "https://example.com/a.gif"

    asyncio.run(run())


def test_get_live_gif_deletes_only_after_two_confirmed_dead(memory_db, monkeypatch):
    async def run():
        gid = await _insert_gif(memory_db, _GUILD, "https://example.com/a.gif")
        monkeypatch.setattr(r2, "check_gif_url_health", lambda *a, **k: "dead")

        assert await gifs_mod.get_live_gif(_GUILD, attempts=1) is None
        cur = await memory_db.execute(
            "SELECT COUNT(*) FROM corpus_gifs WHERE id=?", (gid,)
        )
        assert (await cur.fetchone())[0] == 1  # 1er "dead": todavía no se borra

        assert await gifs_mod.get_live_gif(_GUILD, attempts=1) is None
        cur = await memory_db.execute(
            "SELECT COUNT(*) FROM corpus_gifs WHERE id=?", (gid,)
        )
        assert (await cur.fetchone())[0] == 0  # 2do "dead" seguido: se borra

    asyncio.run(run())

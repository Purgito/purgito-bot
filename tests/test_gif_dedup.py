"""Tests del storage content-addressed de GIFs (r2.upload_gif_sync +
db.gif_objects + db.release_gif_reference).

La invariante que sostiene todo: un mismo archivo ocupa UN objeto en R2, y ese
objeto se borra recién cuando la última fila de corpus_gifs que lo referencia
desaparece. Lo fácil de romper acá es el conteo -- doble decremento, borrar un
objeto que otro servidor todavía usa, o sumar dos veces por un mismo GIF -- así
que los tests apuntan sobre todo a eso.

Mismo estilo que test_gif_health.py: SQLite en memoria inyectada en db._db y
monkeypatch de r2, sin tocar data/bot.db ni el bucket real.
"""

import asyncio

import aiosqlite
import pytest

import cogs.gifs as gifs_mod
import db
import r2

_GUILD_A = 1
_GUILD_B = 2
_HASH = "a" * 64
_OTHER_HASH = "b" * 64


@pytest.fixture
def memory_db(monkeypatch):
    conn = asyncio.run(_open_memory_db())
    monkeypatch.setattr(db, "_db", conn)
    yield conn
    asyncio.run(conn.close())


@pytest.fixture
def deleted_keys(monkeypatch):
    """Registra qué objetos se habrían borrado del bucket."""
    keys: list[str] = []

    async def fake_delete_key(key):
        keys.append(key)

    async def fake_delete_url(url):
        keys.append(url)

    monkeypatch.setattr(r2, "delete_key", fake_delete_key)
    monkeypatch.setattr(r2, "delete_url", fake_delete_url)
    return keys


async def _open_memory_db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(db.SCHEMA)
    await conn.commit()
    return conn


async def _ref_count(conn, content_hash) -> int | None:
    async with conn.execute(
        "SELECT ref_count FROM gif_objects WHERE content_hash=?", (content_hash,)
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


def _url(content_hash: str) -> str:
    return f"https://cdn.example.com/{r2.gif_key(content_hash)}"


# ---------- r2: key content-addressed ----------


def test_gif_key_is_sharded_and_ignores_guild():
    key = r2.gif_key(_HASH)
    assert key == f"gifs/aa/{_HASH}.gif"
    # Nada de guild_id en la key: es lo que permite compartir el objeto.
    assert str(_GUILD_A) not in key


def test_upload_hashes_content_not_url(monkeypatch):
    """El mismo archivo con dos URLs de Discord distintas (repost) tiene que
    dar el mismo hash y por lo tanto la misma key -- la causa raíz del
    problema era hashear la URL, que es efímera y única por mensaje."""
    puts = []

    class _FakeClient:
        def head_object(self, **kw):
            raise LookupError("no existe")

        def put_object(self, **kw):
            puts.append(kw["Key"])

    class _FakeResp:
        status_code = 200
        headers: dict = {}
        content = b"GIF89a-los-mismos-bytes"

        def iter_content(self, chunk_size=None):
            yield self.content

        def close(self):
            pass

    monkeypatch.setattr(r2, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(r2, "_bucket", lambda: "bucket")
    monkeypatch.setattr(r2, "public_url", lambda: "https://cdn.example.com")
    monkeypatch.setattr(r2.requests, "get", lambda *a, **k: _FakeResp())

    a = r2.upload_gif_sync("https://cdn.discordapp.com/attachments/1/2/x.gif?ex=aaa")
    b = r2.upload_gif_sync("https://cdn.discordapp.com/attachments/9/9/x.gif?ex=zzz")
    assert a.content_hash == b.content_hash
    assert a.url == b.url
    assert a.size_bytes == len(_FakeResp.content)
    assert puts == [r2.gif_key(a.content_hash)] * 2


def test_upload_skips_put_when_object_already_exists(monkeypatch):
    puts = []

    class _FakeClient:
        def head_object(self, **kw):
            return {"ContentLength": 10}

        def put_object(self, **kw):
            puts.append(kw["Key"])

    class _FakeResp:
        status_code = 200
        headers: dict = {}
        content = b"GIF89a-repost"

        def iter_content(self, chunk_size=None):
            yield self.content

        def close(self):
            pass

    monkeypatch.setattr(r2, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(r2, "_bucket", lambda: "bucket")
    monkeypatch.setattr(r2, "public_url", lambda: "https://cdn.example.com")
    monkeypatch.setattr(r2.requests, "get", lambda *a, **k: _FakeResp())

    up = r2.upload_gif_sync("https://cdn.discordapp.com/attachments/1/2/x.gif")
    assert up.content_hash
    assert puts == []  # ya estaba en el bucket: no se re-sube


# ---------- r2: descarga acotada y sin redirects (Sección 4) ----------


def test_upload_bounds_memory_when_content_length_is_missing_or_dishonest(
    monkeypatch,
):
    """Sin Content-Length (o si miente), no puede bufferear el cuerpo entero
    en memoria antes de rechazarlo -- tiene que cortar la lectura apenas se
    supera el límite, no agotar la respuesta primero."""
    monkeypatch.setenv("MAX_GIF_DOWNLOAD_BYTES", "1000")
    pulled: list[int] = []

    class _FakeUnboundedResp:
        status_code = 200
        headers: dict = {}  # sin Content-Length

        def iter_content(self, chunk_size=None):
            for _ in range(10_000):  # "infinito" a efectos prácticos del test
                pulled.append(1)
                yield b"x" * 500

        def close(self):
            pass

    client = _FakeUploadClient(exists=False)
    monkeypatch.setattr(r2, "get_client", lambda: client)
    monkeypatch.setattr(r2, "_bucket", lambda: "bucket")
    monkeypatch.setattr(r2, "public_url", lambda: "https://cdn.example.com")
    monkeypatch.setattr(r2.requests, "get", lambda *a, **k: _FakeUnboundedResp())

    up = r2.upload_gif_sync("https://cdn.discordapp.com/x.gif")

    assert up == r2.GifUpload(r2.GIF_TOO_LARGE)
    assert len(pulled) < 10  # se cortó bien lejos de agotar el generador
    assert client.puts == []


def test_upload_does_not_follow_redirects(monkeypatch):
    """El host (cdn.discordapp.com) se valida sobre la URL ORIGINAL en el
    caller (cogs/gifs.py), antes de llegar acá -- si se siguiera un
    redirect a ciegas, ese chequeo no cubriría el destino real de la
    descarga. Un redirect no seguido cae en el mismo camino que cualquier
    otro status distinto de 200: no se sube nada."""
    calls: list[bool | None] = []

    class _RedirectResp:
        status_code = 302
        headers = {"Location": "http://169.254.169.254/latest/meta-data/"}

        def close(self):
            pass

    def fake_get(url, headers=None, timeout=None, stream=None, allow_redirects=None):
        calls.append(allow_redirects)
        return _RedirectResp()

    monkeypatch.setattr(r2, "get_client", lambda: _FakeUploadClient())
    monkeypatch.setattr(r2.requests, "get", fake_get)

    result = r2.upload_gif_sync("https://cdn.discordapp.com/x.gif")

    assert calls == [False]
    assert result is None


# ---------- r2: bloqueo de IP privada / DNS rebinding (Sección 4, ronda 2) ----------
#
# Defensa en profundidad: hoy no hay ruta explotable (el único caller real ya
# valida el hostname exacto contra cdn.discordapp.com antes de llegar acá),
# pero un caller futuro menos cuidadoso no debería poder usar upload_gif_sync
# para tocar un servicio interno.


def test_public_ip_for_host_accepts_public_address(monkeypatch):
    monkeypatch.setattr(
        r2.socket,
        "getaddrinfo",
        lambda *a, **k: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    assert r2._public_ip_for_host("example.com") == "93.184.216.34"


def test_public_ip_for_host_rejects_loopback_and_private_and_link_local(monkeypatch):
    for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254"):
        monkeypatch.setattr(
            r2.socket,
            "getaddrinfo",
            lambda *a, ip=ip, **k: [(None, None, None, None, (ip, 0))],
        )
        assert r2._public_ip_for_host("evil.example.com") is None


def test_public_ip_for_host_skips_private_and_returns_first_public(monkeypatch):
    """Un hostname con varios registros A -- alcanza con que UNO sea privado
    para que el rebinding funcione, así que se busca hasta encontrar el
    primero público en vez de fallar en el primer resultado."""
    monkeypatch.setattr(
        r2.socket,
        "getaddrinfo",
        lambda *a, **k: [
            (None, None, None, None, ("127.0.0.1", 0)),
            (None, None, None, None, ("93.184.216.34", 0)),
        ],
    )
    assert r2._public_ip_for_host("mixed.example.com") == "93.184.216.34"


def test_public_ip_for_host_returns_none_on_dns_failure(monkeypatch):
    def raise_gaierror(*a, **k):
        raise r2.socket.gaierror("no se pudo resolver")

    monkeypatch.setattr(r2.socket, "getaddrinfo", raise_gaierror)
    assert r2._public_ip_for_host("no-existe.invalid") is None


def test_upload_rejects_host_resolving_to_private_ip(monkeypatch):
    """Un hostname que resuelve a loopback/LAN/link-local nunca debe llegar
    a requests.get -- ni siquiera se intenta la descarga."""
    monkeypatch.setattr(r2, "get_client", lambda: _FakeUploadClient())
    monkeypatch.setattr(
        r2.socket,
        "getaddrinfo",
        lambda *a, **k: [(None, None, None, None, ("169.254.169.254", 0))],
    )
    called = []
    monkeypatch.setattr(
        r2.requests, "get", lambda *a, **k: called.append(1) or _FakeUploadResp(b"x")
    )

    result = r2.upload_gif_sync("https://cdn.discordapp.com/x.gif")

    assert result is None
    assert called == []


def test_upload_pins_dns_to_the_validated_ip(monkeypatch):
    """Simula un rebinding real: el resolver "real" da una IP pública en la
    validación inicial pero, para cuando se conecta, ya cambió a una IP
    privada. Sin pinning, la conexión resolvería de nuevo y caería en la
    trampa; con pinning tiene que seguir usando la IP ya validada."""
    client = _FakeUploadClient()
    _patch_upload(monkeypatch, client, b"GIF89a-datos")

    real_answers = iter(["93.184.216.34", "169.254.169.254"])

    def rebinding_getaddrinfo(host, *a, **k):
        # Un IP literal (como el que pasa _pinned) se resuelve a sí mismo,
        # igual que el socket.getaddrinfo real -- solo un hostname de verdad
        # dispara una nueva consulta "DNS" (y, en este mock, la respuesta
        # rebindeada).
        try:
            r2.ipaddress.ip_address(host)
            return [(None, None, None, None, (host, 0))]
        except ValueError:
            return [(None, None, None, None, (next(real_answers), 0))]

    monkeypatch.setattr(r2.socket, "getaddrinfo", rebinding_getaddrinfo)

    seen_during_request = {}

    def spying_get(*a, **k):
        # Mientras la "conexión" está en curso, getaddrinfo tiene que
        # devolver la IP ya pinneada, no volver a resolver (lo que daría la
        # IP rebindeada, la segunda del iterador).
        seen_during_request["ip"] = r2.socket.getaddrinfo("cdn.discordapp.com", None)[
            0
        ][4][0]
        return _FakeUploadResp(b"GIF89a-datos")

    monkeypatch.setattr(r2.requests, "get", spying_get)

    up = r2.upload_gif_sync("https://cdn.discordapp.com/x.gif")

    assert up is not None
    assert seen_during_request["ip"] == "93.184.216.34"
    # Fuera del bloque de la request, getaddrinfo vuelve a ser el mock
    # original (no queda parchado globalmente después de la llamada).
    assert r2.socket.getaddrinfo is rebinding_getaddrinfo


# ---------- cogs.gifs: concurrencia acotada de subidas (Sección 4, ronda 2) ----------
#
# r2.upload_gif_sync es caro (descarga + gifsicle + hash) y corre en el
# thread pool default compartido con el resto del bot. save_gif_candidates
# se dispara en on_message para CUALQUIER mensaje de CUALQUIER miembro (no
# hace falta ser admin) -- sin tope, una ráfaga de mensajes con GIFs de
# cdn.discordapp.com podía saturar ese pool para todo el proceso. El fix es
# un semáforo, no un rate limit que descarte: nunca hay que perder un GIF
# legítimo por llegar en ráfaga (ver la investigación del auto-borrado).


def test_upload_throttled_never_exceeds_semaphore_size(monkeypatch):
    """Ninguna llamada a r2.upload_gif_sync debe correr más de
    _UPLOAD_CONCURRENCY veces en simultáneo, sin importar cuántas lleguen
    a la vez -- y ninguna se pierde, solo esperan su turno."""
    import threading
    import time

    gate = threading.Lock()
    state = {"current": 0, "max": 0}

    def fake_upload_sync(url):
        with gate:
            state["current"] += 1
            state["max"] = max(state["max"], state["current"])
        time.sleep(0.05)
        with gate:
            state["current"] -= 1
        return url

    monkeypatch.setattr(r2, "upload_gif_sync", fake_upload_sync)

    async def run():
        return await asyncio.gather(
            *[gifs_mod._upload_gif_throttled(f"https://x/{i}") for i in range(8)]
        )

    results = asyncio.run(run())
    assert results == [f"https://x/{i}" for i in range(8)]
    assert state["max"] <= 2  # tamaño real de _UPLOAD_CONCURRENCY


# ---------- r2: optimización con gifsicle ----------


class _FakeProc:
    def __init__(self, returncode=0, stdout=b""):
        self.returncode = returncode
        self.stdout = stdout


def test_optimize_returns_smaller_output(monkeypatch):
    monkeypatch.setattr(r2.subprocess, "run", lambda *a, **k: _FakeProc(0, b"corto"))
    assert r2.optimize_gif_bytes(b"un gif bastante mas largo") == b"corto"


def test_optimize_keeps_original_when_gifsicle_missing(monkeypatch):
    def missing(*a, **k):
        raise FileNotFoundError("gifsicle")

    monkeypatch.setattr(r2.subprocess, "run", missing)
    assert r2.optimize_gif_bytes(b"GIF89a-original") == b"GIF89a-original"


def test_optimize_keeps_original_on_timeout(monkeypatch):
    def timeout(*a, **k):
        raise r2.subprocess.TimeoutExpired("gifsicle", 60)

    monkeypatch.setattr(r2.subprocess, "run", timeout)
    assert r2.optimize_gif_bytes(b"GIF89a-original") == b"GIF89a-original"


def test_optimize_keeps_original_on_nonzero_exit(monkeypatch):
    """Un archivo que no es GIF de verdad hace fallar a gifsicle: se sube tal
    cual en vez de perder el GIF."""
    monkeypatch.setattr(r2.subprocess, "run", lambda *a, **k: _FakeProc(1, b""))
    assert r2.optimize_gif_bytes(b"no soy un gif") == b"no soy un gif"


def test_optimize_keeps_original_when_result_is_bigger(monkeypatch):
    monkeypatch.setattr(
        r2.subprocess,
        "run",
        lambda *a, **k: _FakeProc(0, b"mucho mas grande que el original"),
    )
    assert r2.optimize_gif_bytes(b"chiquito") == b"chiquito"


def test_lossy_level_is_configurable_and_clamped(monkeypatch):
    cmds = []
    monkeypatch.setattr(
        r2.subprocess,
        "run",
        lambda cmd, **k: cmds.append(cmd) or _FakeProc(0, b"x"),
    )

    monkeypatch.setenv("GIF_LOSSY_LEVEL", "80")
    r2.optimize_gif_bytes(b"un gif largo")
    assert "--lossy=80" in cmds[-1]

    # 0 apaga la pérdida pero deja la optimización sin pérdida.
    monkeypatch.setenv("GIF_LOSSY_LEVEL", "0")
    r2.optimize_gif_bytes(b"un gif largo")
    assert not any(c.startswith("--lossy") for c in cmds[-1])
    assert "--optimize=3" in cmds[-1]

    # Basura o valores absurdos no rompen ni mandan un flag inválido.
    monkeypatch.setenv("GIF_LOSSY_LEVEL", "no-es-un-numero")
    r2.optimize_gif_bytes(b"un gif largo")
    assert "--lossy=30" in cmds[-1]

    monkeypatch.setenv("GIF_LOSSY_LEVEL", "9999")
    r2.optimize_gif_bytes(b"un gif largo")
    assert "--lossy=200" in cmds[-1]


def test_hash_matches_the_optimized_bytes_that_get_uploaded(monkeypatch):
    """El hash tiene que ser el de lo que queda en el bucket: si se calculara
    antes de optimizar, la key no correspondería al contenido subido."""
    import hashlib

    optimized = b"GIF89a-optimizado"
    bodies = {}

    class _FakeClient:
        def head_object(self, **kw):
            raise LookupError("no existe")

        def put_object(self, **kw):
            bodies[kw["Key"]] = kw["Body"]

    class _FakeResp:
        status_code = 200
        headers: dict = {}
        content = b"GIF89a-pesado-sin-optimizar"

        def iter_content(self, chunk_size=None):
            yield self.content

        def close(self):
            pass

    monkeypatch.setattr(r2, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(r2, "_bucket", lambda: "bucket")
    monkeypatch.setattr(r2, "public_url", lambda: "https://cdn.example.com")
    monkeypatch.setattr(r2.requests, "get", lambda *a, **k: _FakeResp())
    monkeypatch.setattr(r2, "optimize_gif_bytes", lambda data: optimized)

    up = r2.upload_gif_sync("https://cdn.discordapp.com/attachments/1/2/x.gif")
    assert up.content_hash == hashlib.sha256(optimized).hexdigest()
    assert up.size_bytes == len(optimized)
    assert bodies[r2.gif_key(up.content_hash)] == optimized


# ---------- db: conteo de referencias ----------


def test_same_gif_in_two_guilds_shares_one_object(memory_db, deleted_keys):
    async def run():
        await db.save_gif_url(_GUILD_A, _url(_HASH), _HASH, 100)
        await db.save_gif_url(_GUILD_B, _url(_HASH), _HASH, 100)

        async with memory_db.execute("SELECT COUNT(*) FROM gif_objects") as cur:
            assert (await cur.fetchone())[0] == 1
        assert await _ref_count(memory_db, _HASH) == 2

    asyncio.run(run())


def test_repost_in_same_guild_does_not_double_count(memory_db, deleted_keys):
    """El guild ya tenía ese GIF: la fila no se inserta de nuevo, así que
    tampoco puede sumar una segunda referencia."""

    async def run():
        inserted_1, _ = await db.save_gif_url(_GUILD_A, _url(_HASH), _HASH, 100)
        inserted_2, _ = await db.save_gif_url(_GUILD_A, _url(_HASH), _HASH, 100)
        assert inserted_1 is True
        assert inserted_2 is False
        assert await _ref_count(memory_db, _HASH) == 1

    asyncio.run(run())


def test_release_keeps_object_while_other_guild_still_references_it(
    memory_db, deleted_keys
):
    async def run():
        await db.save_gif_url(_GUILD_A, _url(_HASH), _HASH, 100)
        await db.save_gif_url(_GUILD_B, _url(_HASH), _HASH, 100)

        await db.release_gif_reference(_HASH, _url(_HASH))
        assert await _ref_count(memory_db, _HASH) == 1
        assert deleted_keys == []  # todavía lo usa el otro servidor

        await db.release_gif_reference(_HASH, _url(_HASH))
        assert await _ref_count(memory_db, _HASH) is None
        assert deleted_keys == [r2.gif_key(_HASH)]

    asyncio.run(run())


def test_release_twice_past_zero_does_not_redelete(memory_db, deleted_keys):
    """Un decremento de más (bug futuro, retry, doble callback) no debe dejar
    el contador en negativo ni disparar un segundo delete_object."""

    async def run():
        await db.save_gif_url(_GUILD_A, _url(_HASH), _HASH, 100)
        await db.release_gif_reference(_HASH, _url(_HASH))
        await db.release_gif_reference(_HASH, _url(_HASH))
        assert deleted_keys == [r2.gif_key(_HASH)]

    asyncio.run(run())


def test_release_without_hash_falls_back_to_delete_by_url(memory_db, deleted_keys):
    """Filas viejas (pre-dedup) y GIFs de tenor/giphy no tienen content_hash:
    se borran por URL como siempre -- para tenor/giphy delete_url es no-op."""

    async def run():
        await db.release_gif_reference(None, "https://tenor.com/view/x")
        assert deleted_keys == ["https://tenor.com/view/x"]

    asyncio.run(run())


def test_delete_from_panel_releases_reference(memory_db, deleted_keys):
    async def run():
        await db.save_gif_url(_GUILD_A, _url(_HASH), _HASH, 100)
        await db.save_gif_url(_GUILD_B, _url(_HASH), _HASH, 100)
        gif = await db.get_gif_by_url(_GUILD_A, _url(_HASH))

        assert await db.delete_gif_url_by_id(_GUILD_A, gif["id"]) is True
        assert await _ref_count(memory_db, _HASH) == 1
        assert deleted_keys == []

    asyncio.run(run())


def test_health_check_delete_releases_reference(memory_db, deleted_keys):
    async def run():
        await db.save_gif_url(_GUILD_A, _url(_HASH), _HASH, 100)
        gif = await db.get_gif_by_url(_GUILD_A, _url(_HASH))

        assert await db.record_gif_health_check(gif["id"], "dead") is False
        assert await db.record_gif_health_check(gif["id"], "dead") is False
        assert await db.record_gif_health_check(gif["id"], "dead") is True
        assert await _ref_count(memory_db, _HASH) is None
        assert deleted_keys == [r2.gif_key(_HASH)]

    asyncio.run(run())


def test_health_check_keeps_object_used_by_another_guild(memory_db, deleted_keys):
    async def run():
        await db.save_gif_url(_GUILD_A, _url(_HASH), _HASH, 100)
        await db.save_gif_url(_GUILD_B, _url(_HASH), _HASH, 100)
        gif = await db.get_gif_by_url(_GUILD_A, _url(_HASH))

        assert await db.record_gif_health_check(gif["id"], "dead") is False
        assert await db.record_gif_health_check(gif["id"], "dead") is False
        assert await db.record_gif_health_check(gif["id"], "dead") is True
        assert await _ref_count(memory_db, _HASH) == 1
        assert deleted_keys == []

    asyncio.run(run())


def test_wipe_gifs_only_deletes_objects_no_one_else_uses(memory_db, deleted_keys):
    """wipe de un servidor no puede llevarse puestos los objetos que otro
    servidor sigue referenciando."""

    async def run():
        await db.save_gif_url(_GUILD_A, _url(_HASH), _HASH, 100)
        await db.save_gif_url(_GUILD_B, _url(_HASH), _HASH, 100)
        await db.save_gif_url(_GUILD_A, _url(_OTHER_HASH), _OTHER_HASH, 50)

        assert await db.wipe_gifs(_GUILD_A) == 2
        # El compartido sobrevive con la referencia de B; el exclusivo se va.
        assert await _ref_count(memory_db, _HASH) == 1
        assert await _ref_count(memory_db, _OTHER_HASH) is None
        assert deleted_keys == [r2.gif_key(_OTHER_HASH)]

    asyncio.run(run())


def test_save_gif_url_persists_phash_for_new_object(memory_db, deleted_keys):
    async def run():
        await db.save_gif_url(_GUILD_A, _url(_HASH), _HASH, 100, "abc123")
        async with memory_db.execute(
            "SELECT phash FROM gif_objects WHERE content_hash=?", (_HASH,)
        ) as cur:
            row = await cur.fetchone()
        assert row[0] == "abc123"

    asyncio.run(run())


def test_save_gif_url_does_not_overwrite_phash_on_repeat_reference(
    memory_db, deleted_keys
):
    """Otro guild referenciando el mismo objeto (ON CONFLICT) no debe pisar
    el phash ya calculado con None."""

    async def run():
        await db.save_gif_url(_GUILD_A, _url(_HASH), _HASH, 100, "abc123")
        await db.save_gif_url(_GUILD_B, _url(_HASH), _HASH, 100, None)
        async with memory_db.execute(
            "SELECT phash FROM gif_objects WHERE content_hash=?", (_HASH,)
        ) as cur:
            row = await cur.fetchone()
        assert row[0] == "abc123"

    asyncio.run(run())


def test_get_all_gif_phashes_skips_objects_without_phash(memory_db, deleted_keys):
    async def run():
        await db.save_gif_url(_GUILD_A, _url(_HASH), _HASH, 100, "abc123")
        await db.save_gif_url(_GUILD_A, _url(_OTHER_HASH), _OTHER_HASH, 50, None)
        rows = await db.get_all_gif_phashes()
        assert rows == [(_HASH, r2.gif_key(_HASH), "abc123")]

    asyncio.run(run())


def test_eviction_releases_reference(memory_db, deleted_keys, monkeypatch):
    """Al llegar al tope de la colección se desaloja el más viejo: eso también
    tiene que soltar su referencia, no borrar el objeto a ciegas."""
    monkeypatch.setattr(db, "_limit_for_guild", lambda *a, **k: 1)

    async def run():
        await db.save_gif_url(_GUILD_A, _url(_HASH), _HASH, 100)
        await db.save_gif_url(_GUILD_B, _url(_HASH), _HASH, 100)
        # Guild A llega al tope: entra el nuevo, sale el compartido.
        _, evicted_id = await db.save_gif_url(
            _GUILD_A, _url(_OTHER_HASH), _OTHER_HASH, 50
        )
        assert evicted_id is not None
        assert await _ref_count(memory_db, _HASH) == 1
        assert deleted_keys == []

    asyncio.run(run())


# ---------- r2: phash perceptual ----------


def _make_gif_bytes(color) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color=color).save(buf, format="GIF")
    return buf.getvalue()


def test_compute_phash_returns_hex_string_for_valid_gif():
    phash = r2.compute_phash(_make_gif_bytes((255, 0, 0)))
    assert phash is not None
    assert len(phash) == 16
    int(phash, 16)  # es hex válido


def test_compute_phash_degrades_to_none_on_corrupt_bytes():
    assert r2.compute_phash(b"no soy un gif") is None


def test_compute_phash_enforces_decompression_bomb_cap_regardless_of_prior_state():
    """No puede depender de que meme_generator.py ya se haya importado antes
    en el proceso para tener el límite puesto -- compute_phash tiene que
    fijar su propio Image.MAX_IMAGE_PIXELS cada vez que corre, sin importar
    en qué estado esté al entrar."""
    from PIL import Image

    original = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = None  # simula que nadie lo fijó todavía
        r2.compute_phash(_make_gif_bytes((1, 2, 3)))
        assert Image.MAX_IMAGE_PIXELS == 15_000_000
    finally:
        Image.MAX_IMAGE_PIXELS = original


class _FakeUploadClient:
    def __init__(self, exists=False):
        self._exists = exists
        self.puts = []

    def head_object(self, **kw):
        if not self._exists:
            raise LookupError("no existe")
        return {}

    def put_object(self, **kw):
        self.puts.append(kw["Key"])


class _FakeUploadResp:
    def __init__(self, content):
        self.status_code = 200
        self.headers: dict = {}
        self.content = content

    def iter_content(self, chunk_size=None):
        yield self.content

    def close(self):
        pass


def _patch_upload(monkeypatch, client, content):
    monkeypatch.setattr(r2, "get_client", lambda: client)
    monkeypatch.setattr(r2, "_bucket", lambda: "bucket")
    monkeypatch.setattr(r2, "public_url", lambda: "https://cdn.example.com")
    monkeypatch.setattr(r2.requests, "get", lambda *a, **k: _FakeUploadResp(content))
    monkeypatch.setattr(r2, "optimize_gif_bytes", lambda data: data)


def test_upload_with_exact_match_does_not_compute_phash(monkeypatch):
    client = _FakeUploadClient(exists=True)
    _patch_upload(monkeypatch, client, _make_gif_bytes((0, 255, 0)))
    called = []
    monkeypatch.setattr(r2, "compute_phash", lambda data: called.append(1) or "x")

    up = r2.upload_gif_sync("https://cdn.discordapp.com/x.gif")

    assert called == []
    assert up.phash is None
    assert client.puts == []


def test_upload_without_any_match_uploads_normally_and_keeps_its_own_phash(
    memory_db, monkeypatch
):
    client = _FakeUploadClient(exists=False)
    data = _make_gif_bytes((0, 0, 255))
    _patch_upload(monkeypatch, client, data)

    up = r2.upload_gif_sync("https://cdn.discordapp.com/x.gif")

    assert client.puts == [r2.gif_key(up.content_hash)]
    assert up.phash == r2.compute_phash(data)


def test_upload_with_perceptual_match_reuses_existing_object_without_uploading(
    memory_db, monkeypatch
):
    """Mismo meme, bytes distintos: no hay match exacto por content_hash pero
    sí por phash -- no debe subir un objeto nuevo a R2."""
    data = _make_gif_bytes((10, 10, 10))
    phash = r2.compute_phash(data)
    existing_hash = "c" * 64

    async def seed():
        await memory_db.execute(
            "INSERT INTO gif_objects (content_hash, r2_key, ref_count, size_bytes, phash) "
            "VALUES (?, ?, 1, 10, ?)",
            (existing_hash, r2.gif_key(existing_hash), phash),
        )
        await memory_db.commit()

    asyncio.run(seed())

    client = _FakeUploadClient(exists=False)
    _patch_upload(monkeypatch, client, data)

    up = r2.upload_gif_sync("https://cdn.discordapp.com/x.gif")

    assert client.puts == []  # no se subió nada nuevo
    assert up.content_hash == existing_hash
    assert up.url == f"https://cdn.example.com/{r2.gif_key(existing_hash)}"


def test_upload_ignores_perceptual_matches_beyond_the_configured_distance(
    memory_db, monkeypatch
):
    data = _make_gif_bytes((200, 0, 200))
    existing_hash = "d" * 64

    async def seed():
        # Un phash completamente distinto: no debe matchear.
        await memory_db.execute(
            "INSERT INTO gif_objects (content_hash, r2_key, ref_count, size_bytes, phash) "
            "VALUES (?, ?, 1, 10, ?)",
            (existing_hash, r2.gif_key(existing_hash), "0" * 16),
        )
        await memory_db.commit()

    asyncio.run(seed())
    monkeypatch.setattr(r2, "compute_phash", lambda d: "f" * 16)

    client = _FakeUploadClient(exists=False)
    _patch_upload(monkeypatch, client, data)

    up = r2.upload_gif_sync("https://cdn.discordapp.com/x.gif")

    assert up.content_hash != existing_hash
    assert client.puts == [r2.gif_key(up.content_hash)]


# ---------- Cache-Control (Sección 7, cierre de pendientes) ----------
#
# 1 año era demasiada ventana en la que un objeto ya borrado de R2 (bloqueo
# manual, chequeo de salud, wipe) podía seguir sirviéndose desde el edge de
# Cloudflare. Bajado a 14 días -- sigue siendo agresivo para lo que sigue
# vivo, pero acota la ventana de "borrado que no borra de verdad".


class _CacheControlCapturingClient:
    def __init__(self):
        self.put_kwargs: list[dict] = []

    def head_object(self, **kw):
        raise LookupError("no existe")

    def put_object(self, **kw):
        self.put_kwargs.append(kw)


def test_upload_gif_sync_usa_el_cache_control_de_14_dias(monkeypatch):
    client = _CacheControlCapturingClient()
    _patch_upload(monkeypatch, client, b"GIF89a-datos")

    r2.upload_gif_sync("https://cdn.discordapp.com/x.gif")

    assert len(client.put_kwargs) == 1
    assert client.put_kwargs[0]["CacheControl"] == "public, max-age=1209600, immutable"


def test_upload_image_bytes_sync_usa_el_mismo_cache_control(monkeypatch):
    client = _CacheControlCapturingClient()
    monkeypatch.setattr(r2, "get_client", lambda: client)
    monkeypatch.setattr(r2, "_bucket", lambda: "bucket")
    monkeypatch.setattr(r2, "public_url", lambda: "https://cdn.example.com")

    url = r2.upload_image_bytes_sync("https://x/img.png", b"pngbytes", 1, ".png")

    assert url is not None
    assert len(client.put_kwargs) == 1
    assert client.put_kwargs[0]["CacheControl"] == "public, max-age=1209600, immutable"

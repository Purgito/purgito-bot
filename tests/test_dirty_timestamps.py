"""Fechas malformadas en las queries de vencimiento (meme_schedule,
scheduled_announcements, guild_departures).

SQLite devolvía NULL ante una fecha inválida y la fila simplemente no cumplía
la condición; el cast `::timestamp` de PostgreSQL abortaba la query entera y
con ella a todos los guilds. Con datos válidos el comportamiento es el de
siempre; una fila inválida no puede tumbar a las demás.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import pg_support
import db

FMT = "%Y-%m-%d %H:%M:%S"


def _ago(**kw) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kw)).strftime(FMT)


@pytest.fixture
def conn(monkeypatch):
    c = asyncio.run(pg_support.connect())
    monkeypatch.setattr(db, "_db", c)
    yield c
    asyncio.run(c.close())


def _sql(conn, sql, params=()):
    return asyncio.run(conn.execute(sql, params))


def _meme(conn, guild, last_posted_at, interval=60):
    _sql(
        conn,
        "INSERT INTO meme_schedule (guild_id, channel_id, interval_minutes, last_posted_at) "
        "VALUES (?, 1, ?, ?)",
        (guild, interval, last_posted_at),
    )


def _due_memes():
    return sorted(s["guild_id"] for s in asyncio.run(db.get_due_meme_schedules()))


# --- meme_schedule -----------------------------------------------------------


def test_meme_datos_validos_se_comportan_como_siempre(conn):
    _meme(conn, 1, None)  # nunca posteado: vence
    _meme(conn, 2, _ago(minutes=61))  # pasó el intervalo: vence
    _meme(conn, 3, _ago(minutes=30))  # todavía no
    assert _due_memes() == [1, 2]


@pytest.mark.parametrize(
    "malo",
    [
        "no es una fecha",
        "",
        "2026-13-45 99:99:99",  # con forma de fecha pero imposible
        "0000-00-00 00:00:00",
        "9999-12-31 23:59:59",  # la suma se sale de rango
        "ayer",
    ],
)
def test_meme_una_fila_malformada_no_tumba_a_las_demas(conn, malo):
    _meme(conn, 1, _ago(minutes=61))  # válida y vencida
    _meme(conn, 2, malo)  # inválida
    _meme(conn, 3, _ago(minutes=5))  # válida, no vencida
    due = _due_memes()  # no levanta
    assert 1 in due and 3 not in due


def test_meme_fila_malformada_se_trata_como_vencida_y_se_cura_al_publicar(conn):
    _meme(conn, 2, "basura")
    assert _due_memes() == [2]
    asyncio.run(db.update_meme_last_posted(2, 1))
    assert _due_memes() == []  # ya con fecha válida


def test_meme_intervalo_gigante_no_desborda(conn):
    _meme(conn, 1, _ago(minutes=5), interval=9_000_000_000)
    _meme(conn, 2, _ago(minutes=61))
    assert _due_memes() == [2]


# --- scheduled_announcements -------------------------------------------------


def _anuncio(conn, guild, mode, last_sent_at, interval=None, hour=0, minute=0):
    _sql(
        conn,
        "INSERT INTO scheduled_announcements "
        "(guild_id, channel_id, message, mode, interval_minutes, hour, minute, "
        "last_sent_at, created_by, weekdays) VALUES (?, 1, 'x', ?, ?, ?, ?, ?, 1, ?)",
        (guild, mode, interval, hour, minute, last_sent_at, "0,1,2,3,4,5,6"),
    )


def _due_anuncios():
    return sorted(
        a["guild_id"] for a in asyncio.run(db.get_due_scheduled_announcements())
    )


def test_anuncios_interval_validos(conn):
    _anuncio(conn, 1, "interval", None, interval=10)
    _anuncio(conn, 2, "interval", _ago(minutes=11), interval=10)
    _anuncio(conn, 3, "interval", _ago(minutes=5), interval=10)
    assert _due_anuncios() == [1, 2]


@pytest.mark.parametrize("malo", ["xx", "2026-02-31 10:00:00", "9999-12-31 23:59:59"])
def test_anuncios_interval_malformado_no_tumba_a_los_demas(conn, malo):
    _anuncio(conn, 1, "interval", _ago(minutes=11), interval=10)
    _anuncio(conn, 2, "interval", malo, interval=10)
    _anuncio(conn, 3, "interval", _ago(minutes=1), interval=10)
    due = _due_anuncios()
    assert 1 in due and 3 not in due


def test_anuncios_interval_sin_intervalo_no_vence_aunque_la_fecha_sea_mala(conn):
    # Estado inválido distinto (interval_minutes NULL): sigue sin disparar.
    _anuncio(conn, 1, "interval", "xx", interval=None)
    assert _due_anuncios() == []


def test_anuncios_diarios_con_fecha_malformada_no_tumban_la_lista(conn):
    # El filtro de "ya se envió hoy" se hace en Python: un strptime fallido
    # tampoco puede levantar.
    _anuncio(conn, 1, "daily", "esto no es una fecha")
    _anuncio(conn, 2, "daily", _ago(days=3))
    _anuncio(conn, 3, "interval", _ago(minutes=11), interval=10)
    due = _due_anuncios()
    assert 3 in due and 1 in due and 2 in due  # hora 00:00 ya pasó hoy


# --- guild_departures --------------------------------------------------------


def _salida(conn, guild, left_at):
    _sql(
        conn,
        "INSERT INTO guild_departures (guild_id, left_at) VALUES (?, ?)",
        (guild, left_at),
    )


def test_departures_validos(conn):
    _salida(conn, 1, _ago(days=31))
    _salida(conn, 2, _ago(days=5))
    assert asyncio.run(db.get_expired_departures(30)) == [1]


@pytest.mark.parametrize(
    "malo", ["basura", "2026-99-99 00:00:00", "9999-12-31 23:59:59"]
)
def test_departures_malformada_no_se_purga_ni_tumba_a_las_demas(conn, malo):
    _salida(conn, 1, _ago(days=31))
    _salida(conn, 2, malo)
    # Borrar datos de un guild por una fecha ilegible sería irreversible:
    # la fila inválida NO cuenta como vencida.
    assert asyncio.run(db.get_expired_departures(30)) == [1]


# --- la función SQL ----------------------------------------------------------


def test_utc_text_plus(conn):
    def f(t):
        cur = _sql(conn, "SELECT utc_text_plus(?, make_interval(hours => ?))", (t, 1))
        return asyncio.run(cur.fetchone())[0]

    assert f("2026-10-01 10:00:00") == "2026-10-01 11:00:00"
    assert f("2026-10-01T10:00:00") == "2026-10-01 11:00:00"  # ISO con T también
    assert f(None) is None
    assert f("nada") is None
    assert f("9999-12-31 23:59:59") is None

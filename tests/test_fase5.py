"""Tests de la Fase 5 del editor de embeds: opciones de envío finas
(silencioso / restricción de menciones), formato wrapper de embed_json,
subida de imágenes a R2 (sniffing + dedup por contenido, ahora en
embeds_core.py) y custom_ids distintos al duplicar botones de rol. DB SQLite en memoria, sin tocar
data/bot.db."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import discord
import pytest

import db
import embeds_core
import r2
from cogs.anuncios import Anuncios
from layout_v2 import assign_button_custom_ids
from message_options import sanitize_send_options, send_kwargs


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


# ─── sanitize_send_options / send_kwargs ─────────────────────────────────────


def test_sanitize_defaults_returns_none():
    assert sanitize_send_options(None) is None
    assert sanitize_send_options({}) is None
    assert sanitize_send_options({"silent": False, "restrict_mentions": False}) is None


def test_sanitize_parses_and_caps_roles():
    out = sanitize_send_options(
        {
            "silent": True,
            "restrict_mentions": True,
            "allowed_role_ids": ["12", 34, "x", None],
        }
    )
    assert out == {
        "silent": True,
        "restrict_mentions": True,
        "allowed_role_ids": [12, 34],
        "username": "",
        "avatar_url": "",
    }
    # tope defensivo del listado
    out = sanitize_send_options(
        {"restrict_mentions": True, "allowed_role_ids": list(range(50))}
    )
    assert len(out["allowed_role_ids"]) == 20


def test_send_kwargs_silent_only():
    kw = send_kwargs(
        {"silent": True, "restrict_mentions": False, "allowed_role_ids": []}
    )
    assert kw == {"silent": True}


def test_send_kwargs_restrict_no_roles_pings_nobody():
    kw = send_kwargs(
        {"silent": False, "restrict_mentions": True, "allowed_role_ids": []}
    )
    am = kw["allowed_mentions"]
    assert am.everyone is False and am.users is False and am.roles is False
    assert "silent" not in kw


def test_send_kwargs_restrict_with_roles():
    kw = send_kwargs(
        {"silent": True, "restrict_mentions": True, "allowed_role_ids": [7, 8]}
    )
    assert kw["silent"] is True
    assert [r.id for r in kw["allowed_mentions"].roles] == [7, 8]


def test_send_kwargs_none_is_empty():
    assert send_kwargs(None) == {}


# ─── Formato wrapper de embed_json + extract_send_options ────────────────────


def test_normalize_wrapper_format():
    raw = json.dumps({"embeds": [{"title": "a"}], "send_options": {"silent": True}})
    assert db.normalize_embeds_json(raw) == [{"title": "a"}]


def test_extract_send_options_from_wrapper_and_layout():
    wrapper = json.dumps({"embeds": [], "send_options": {"silent": True}})
    layout = json.dumps({"blocks": [], "send_options": {"restrict_mentions": True}})
    assert db.extract_send_options(wrapper) == {"silent": True}
    assert db.extract_send_options(layout) == {"restrict_mentions": True}


def test_extract_send_options_absent():
    assert db.extract_send_options('[{"title": "t"}]') is None  # lista plana
    assert db.extract_send_options('{"title": "t"}') is None  # dict legacy
    assert db.extract_send_options(None) is None
    assert db.extract_send_options("no json") is None


# ─── Anuncios programados: opciones aplicadas en el envío ────────────────────


def _fake_channel():
    channel = MagicMock(spec=discord.TextChannel)
    # Todos los anuncios de este archivo se programan con guild_id=1 (ver
    # add_scheduled_announcement más abajo); check_announcements ahora
    # verifica channel.guild.id contra esa fila (sección 9 ronda 3).
    channel.guild = SimpleNamespace(id=1, me=MagicMock())
    perms = MagicMock()
    perms.send_messages = True
    perms.embed_links = True
    channel.permissions_for.return_value = perms
    channel.send = AsyncMock()
    return channel


def _run_loop(channel):
    bot = MagicMock()
    bot.get_channel.return_value = channel
    cog = Anuncios(bot)
    asyncio.run(cog.check_announcements.coro(cog))


def test_scheduled_classic_with_send_options(memory_db):
    payload = json.dumps(
        {
            "embeds": [{"title": "aviso"}],
            "send_options": {
                "silent": True,
                "restrict_mentions": True,
                "allowed_role_ids": [5],
            },
        }
    )
    asyncio.run(
        db.add_scheduled_announcement(
            1,
            10,
            "aviso",
            "interval",
            1,
            interval_minutes=30,
            embed_json=payload,
        )
    )
    channel = _fake_channel()
    _run_loop(channel)
    kwargs = channel.send.await_args.kwargs
    assert kwargs["silent"] is True
    assert [r.id for r in kwargs["allowed_mentions"].roles] == [5]
    assert [e.title for e in kwargs["embeds"]] == ["aviso"]


def test_scheduled_layout_with_send_options(memory_db):
    payload = json.dumps(
        {
            "blocks": [{"type": "text", "content": "hola"}],
            "send_options": {"silent": True},
        }
    )
    asyncio.run(
        db.add_scheduled_announcement(
            1,
            10,
            "[layout]",
            "interval",
            1,
            interval_minutes=30,
            embed_json=payload,
            content_mode="layout_v2",
        )
    )
    channel = _fake_channel()
    _run_loop(channel)
    kwargs = channel.send.await_args.kwargs
    assert kwargs["silent"] is True
    assert isinstance(kwargs["view"], discord.ui.LayoutView)


def test_scheduled_without_options_sends_plain_kwargs(memory_db):
    asyncio.run(
        db.add_scheduled_announcement(
            1,
            10,
            "aviso",
            "interval",
            1,
            interval_minutes=30,
            embed_json='[{"title": "sin opciones"}]',
        )
    )
    channel = _fake_channel()
    _run_loop(channel)
    kwargs = channel.send.await_args.kwargs
    assert "silent" not in kwargs and "allowed_mentions" not in kwargs


# ─── Subida de imágenes: sniffing y dedup por contenido ──────────────────────

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 32


def test_sniff_image_formats():
    assert embeds_core.sniff_image(PNG) == ".png"
    assert embeds_core.sniff_image(JPG) == ".jpg"
    assert embeds_core.sniff_image(GIF) == ".gif"
    assert embeds_core.sniff_image(WEBP) == ".webp"
    assert embeds_core.sniff_image(b"hola esto no es una imagen") is None
    assert embeds_core.sniff_image(b"") is None


def test_store_upload_same_bytes_same_url(monkeypatch):
    calls = []

    def fake_upload(url, data, guild_id, ext):
        calls.append(url)
        return f"https://pub.example/{guild_id}/{url.split(':')[1]}{ext}"

    monkeypatch.setattr(r2, "upload_image_bytes_sync", fake_upload)
    url1 = asyncio.run(embeds_core.store_upload(PNG, 1, ".png"))
    url2 = asyncio.run(embeds_core.store_upload(PNG, 1, ".png"))
    # Misma imagen -> misma key derivada del contenido -> misma URL (el
    # segundo put pisa el primero en R2, no queda objeto duplicado).
    assert url1 == url2
    assert calls[0] == calls[1]
    # Contenido distinto -> URL distinta.
    url3 = asyncio.run(embeds_core.store_upload(GIF, 1, ".gif"))
    assert url3 != url1


# ─── Duplicación de botones de rol: custom_id siempre distinto ───────────────


def test_duplicated_role_buttons_get_distinct_custom_ids():
    # Simula el flujo de "duplicar bloque" del panel: la copia llega al backend
    # sin custom_id (el frontend los limpia) y el minteo genera ids distintos.
    layout = {
        "blocks": [
            {
                "type": "action_row",
                "buttons": [{"style": "role", "label": "a", "role_id": 1}],
            },
            {
                "type": "action_row",
                "buttons": [{"style": "role", "label": "a", "role_id": 1}],
            },
        ]
    }
    assigned = assign_button_custom_ids(layout)
    ids = [a["custom_id"] for a in assigned]
    assert len(ids) == 2 and len(set(ids)) == 2

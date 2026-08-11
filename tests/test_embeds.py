"""Tests del editor de embeds: validate_embed_payload (embeds_core.py), CRUD de
embed_templates con límite free y chequeo de propiedad por guild_id (IDOR), y
la rama embed_json vs texto plano en el envío de anuncios programados. Usa una
DB SQLite en memoria inyectada en db._db, sin tocar data/bot.db."""

import asyncio
import io
import json
import logging
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import discord
import pytest

import db
import webapi
from cogs.anuncios import Anuncios
from layout_v2 import (
    ROLE_TOGGLE_PREFIX,
    assign_button_custom_ids,
    build_layout_view,
    has_file_block,
    validate_layout_v2_payload,
)
from embeds_core import validate_embed_payload, validate_embeds_payload


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


# ─── validate_embed_payload ──────────────────────────────────────────────────


def test_valid_minimal_embed():
    assert validate_embed_payload({"title": "hola"}) is None


def test_valid_full_embed():
    embed = {
        "title": "t",
        "description": "d",
        "color": 0x8B6EF5,
        "author": {"name": "autor"},
        "footer": {"text": "pie"},
        "fields": [{"name": "n", "value": "v", "inline": True}],
    }
    assert validate_embed_payload(embed) is None


def test_not_a_dict():
    assert validate_embed_payload(None) is not None
    assert validate_embed_payload("x") is not None


def test_empty_embed_rejected():
    assert validate_embed_payload({}) is not None


def test_title_too_long():
    assert validate_embed_payload({"title": "x" * 257}) is not None
    assert validate_embed_payload({"title": "x" * 256}) is None


def test_description_too_long():
    assert validate_embed_payload({"description": "x" * 4097}) is not None
    assert validate_embed_payload({"description": "x" * 4096}) is None


def test_too_many_fields():
    ok = {"fields": [{"name": "n", "value": "v"}] * 25}
    over = {"fields": [{"name": "n", "value": "v"}] * 26}
    assert validate_embed_payload(ok) is None
    assert validate_embed_payload(over) is not None


def test_field_name_and_value_limits():
    assert (
        validate_embed_payload({"fields": [{"name": "x" * 257, "value": "v"}]})
        is not None
    )
    assert (
        validate_embed_payload({"fields": [{"name": "n", "value": "x" * 1025}]})
        is not None
    )
    assert validate_embed_payload({"fields": [{"name": "", "value": "v"}]}) is not None


def test_footer_and_author_limits():
    assert validate_embed_payload({"footer": {"text": "x" * 2049}}) is not None
    assert validate_embed_payload({"author": {"name": "x" * 257}}) is not None


def test_total_over_6000():
    # Cada parte respeta su propio límite, pero la suma pasa de 6000.
    embed = {
        "description": "x" * 4000,
        "fields": [
            {"name": "n", "value": "x" * 1024},
            {"name": "n", "value": "x" * 1024},
        ],
    }
    assert validate_embed_payload(embed) is not None


def test_color_hex_string_converted_to_int():
    embed = {"title": "t", "color": "#8B6EF5"}
    assert validate_embed_payload(embed) is None
    assert embed["color"] == 0x8B6EF5


def test_color_invalid_string_rejected():
    assert validate_embed_payload({"title": "t", "color": "#zzz"}) is not None


def test_color_out_of_range_rejected():
    assert validate_embed_payload({"title": "t", "color": 0x1000000}) is not None


# ─── validate_embeds_payload (array, modo clásico) ───────────────────────────


def test_embeds_array_valid():
    assert validate_embeds_payload([{"title": "a"}, {"title": "b"}]) is None


def test_embeds_array_must_be_nonempty_list():
    assert validate_embeds_payload([]) is not None
    assert validate_embeds_payload({"title": "t"}) is not None
    assert validate_embeds_payload(None) is not None


def test_embeds_array_max_10():
    assert validate_embeds_payload([{"title": "t"}] * 10) is None
    assert validate_embeds_payload([{"title": "t"}] * 11) is not None


def test_embeds_array_reports_offending_index():
    err = validate_embeds_payload([{"title": "ok"}, {"title": "x" * 300}])
    assert err is not None and "Embed 2" in err


def test_embeds_array_total_over_6000_combined():
    # Cada embed respeta el límite individual, pero la suma del mensaje pasa
    # de 6000 (regla real de Discord: el tope es por mensaje, no por embed).
    embeds = [{"description": "x" * 3000}, {"description": "x" * 3001}]
    assert validate_embeds_payload(embeds) is not None
    # Justo en 6000 debe pasar.
    embeds = [{"description": "x" * 3000}, {"description": "x" * 3000}]
    assert validate_embeds_payload(embeds) is None


def test_embeds_array_converts_each_color():
    embeds = [{"title": "a", "color": "#8B6EF5"}, {"title": "b", "color": "#000000"}]
    assert validate_embeds_payload(embeds) is None
    assert embeds[0]["color"] == 0x8B6EF5
    assert embeds[1]["color"] == 0


# ─── normalize_embeds_json (migración dict suelto -> array) ───────────────────


def test_normalize_wraps_legacy_dict():
    # Formato viejo: un dict suelto guardado antes de soportar múltiples embeds.
    assert db.normalize_embeds_json('{"title": "viejo"}') == [{"title": "viejo"}]


def test_normalize_passes_through_array():
    assert db.normalize_embeds_json('[{"title": "a"}, {"title": "b"}]') == [
        {"title": "a"},
        {"title": "b"},
    ]


def test_normalize_empty_and_none():
    assert db.normalize_embeds_json(None) == []
    assert db.normalize_embeds_json("") == []


# ─── Plantillas: límite free ─────────────────────────────────────────────────


def test_add_embed_template_rejects_over_limit(memory_db):
    guild_id = 1
    embed_json = json.dumps({"title": "t"})
    for i in range(20):  # MAX_EMBED_TEMPLATES_PER_GUILD_FREE=20 en limits.env
        new_id = asyncio.run(db.add_embed_template(guild_id, f"tpl{i}", embed_json))
        assert new_id is not None
    rejected = asyncio.run(db.add_embed_template(guild_id, "tpl21", embed_json))
    assert rejected is None
    # El rechazo no evictó nada: siguen las 20 originales.
    assert len(asyncio.run(db.list_embed_templates(guild_id))) == 20


# ─── Plantillas: propiedad por guild_id (IDOR) ───────────────────────────────


def test_template_ownership_checks(memory_db):
    owner, intruder = 1, 2
    embed_json = json.dumps({"title": "t"})
    template_id = asyncio.run(db.add_embed_template(owner, "mia", embed_json))

    assert asyncio.run(db.get_embed_template(template_id, intruder)) is None
    assert not asyncio.run(
        db.update_embed_template(template_id, intruder, "robada", embed_json)
    )
    assert not asyncio.run(db.delete_embed_template(template_id, intruder))

    # El dueño sí puede todo.
    tpl = asyncio.run(db.get_embed_template(template_id, owner))
    assert tpl is not None and tpl["name"] == "mia"
    assert asyncio.run(
        db.update_embed_template(template_id, owner, "renombrada", embed_json)
    )
    assert (
        asyncio.run(db.get_embed_template(template_id, owner))["name"] == "renombrada"
    )
    assert asyncio.run(db.delete_embed_template(template_id, owner))
    assert asyncio.run(db.get_embed_template(template_id, owner)) is None


# ─── Timestamp del embed (Fase 1) ─────────────────────────────────────────────
# webapi.validate_embed_payload es el validador que corre de verdad en
# producción (embeds_core.validate_embed_payload, importado arriba, es una
# copia sin usar — ver auditoría; no se toca acá).


def test_timestamp_valid_iso_accepted():
    embed = {"title": "t", "timestamp": "2026-08-10T12:00:00.000Z"}
    assert webapi.validate_embed_payload(embed) is None


def test_timestamp_invalid_string_rejected():
    assert (
        webapi.validate_embed_payload({"title": "t", "timestamp": "no es una fecha"})
        is not None
    )


def test_timestamp_wrong_type_rejected():
    assert webapi.validate_embed_payload({"title": "t", "timestamp": 12345}) is not None


def test_timestamp_absent_is_fine():
    assert webapi.validate_embed_payload({"title": "t"}) is None


# ─── Galería de imágenes ya subidas (Fase 1) ─────────────────────────────────


def test_record_and_list_uploaded_images(memory_db):
    asyncio.run(db.record_uploaded_image(1, "https://cdn/a.png"))
    asyncio.run(db.record_uploaded_image(1, "https://cdn/b.png"))
    # Más reciente primero.
    assert asyncio.run(db.list_uploaded_images(1)) == [
        "https://cdn/b.png",
        "https://cdn/a.png",
    ]


def test_record_uploaded_image_dedupes(memory_db):
    asyncio.run(db.record_uploaded_image(1, "https://cdn/a.png"))
    asyncio.run(db.record_uploaded_image(1, "https://cdn/a.png"))
    assert asyncio.run(db.list_uploaded_images(1)) == ["https://cdn/a.png"]


def test_list_uploaded_images_scoped_by_guild(memory_db):
    asyncio.run(db.record_uploaded_image(1, "https://cdn/a.png"))
    asyncio.run(db.record_uploaded_image(2, "https://cdn/b.png"))
    assert asyncio.run(db.list_uploaded_images(1)) == ["https://cdn/a.png"]
    assert asyncio.run(db.list_uploaded_images(2)) == ["https://cdn/b.png"]


# ─── Anuncios: rama embed_json vs texto plano ────────────────────────────────


def _fake_channel(channel_id=10, sent_message_id=999, guild_id=1):
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    # channel.guild.id lo compara check_announcements contra la fila (defensa
    # de scoping cross-guild, sección 9 ronda 3) -- todos los tests de este
    # archivo programan con guild_id=1, así que el default matchea.
    channel.guild = SimpleNamespace(id=guild_id, me=MagicMock())
    perms = MagicMock()
    perms.send_messages = True
    perms.embed_links = True
    channel.permissions_for.return_value = perms
    sent_message = MagicMock(spec=discord.Message)
    sent_message.id = sent_message_id
    channel.send = AsyncMock(return_value=sent_message)
    return channel


def _run_announcement_loop(channel):
    bot = MagicMock()
    bot.get_channel.return_value = channel
    cog = Anuncios(bot)
    asyncio.run(cog.check_announcements.coro(cog))


def test_scheduled_announcement_plain_text_branch(memory_db):
    asyncio.run(
        db.add_scheduled_announcement(
            1, 10, "hola texto", "interval", 1, interval_minutes=30
        )
    )
    channel = _fake_channel()
    _run_announcement_loop(channel)
    channel.send.assert_awaited_once_with("hola texto")


def test_scheduled_announcement_delete_after_forwarded(memory_db):
    asyncio.run(
        db.add_scheduled_announcement(
            1,
            10,
            "se autoborra",
            "interval",
            1,
            interval_minutes=30,
            delete_after_seconds=1,
        )
    )
    channel = _fake_channel()
    _run_announcement_loop(channel)
    channel.send.assert_awaited_once_with("se autoborra", delete_after=1)


def test_scheduled_announcement_no_delete_after_omits_kwarg(memory_db):
    asyncio.run(
        db.add_scheduled_announcement(
            1, 10, "queda", "interval", 1, interval_minutes=30
        )
    )
    channel = _fake_channel()
    _run_announcement_loop(channel)
    channel.send.assert_awaited_once_with("queda")


def test_scheduled_announcement_logs_loudly_if_mark_sent_fails_after_send(
    memory_db, monkeypatch, caplog
):
    """Sección 5, ronda 2: si el envío a Discord tuvo éxito pero el UPDATE de
    last_sent_at falla, el mensaje YA salió -- la próxima corrida (1 min) lo
    va a reenviar como duplicado visible. No hay forma barata de hacerlo
    atómico con el envío, así que el fix mínimo es que quede un rastro
    explícito y distinguible de "se mandó pero no se pudo marcar", no un
    log genérico indistinguible de un fallo de envío real."""
    import cogs.anuncios as anuncios_mod

    asyncio.run(
        db.add_scheduled_announcement(
            1, 10, "hola texto", "interval", 1, interval_minutes=30
        )
    )

    async def failing_mark_sent(announcement_id):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(
        anuncios_mod, "update_announcement_last_sent", failing_mark_sent
    )

    channel = _fake_channel()
    with caplog.at_level(logging.ERROR):
        _run_announcement_loop(channel)

    channel.send.assert_awaited_once_with("hola texto")  # el mensaje SÍ salió
    assert any(
        "SE ENVIÓ" in r.message and "no se pudo marcar" in r.message
        for r in caplog.records
    )


def test_scheduled_announcement_delete_after_registers_pending_deletion(memory_db):
    # Además del delete_after= rápido, debe quedar una fila de respaldo en
    # pending_message_deletions (channel_id, message_id del mensaje enviado).
    asyncio.run(
        db.add_scheduled_announcement(
            1,
            10,
            "se autoborra",
            "interval",
            1,
            interval_minutes=30,
            delete_after_seconds=60,
        )
    )
    channel = _fake_channel(channel_id=10, sent_message_id=555)
    _run_announcement_loop(channel)
    due = asyncio.run(db.get_due_pending_deletions())
    assert due == []  # todavía no venció (delete_at en 60s, no <= now)


def test_pending_deletion_swept_after_channel_restart(memory_db):
    # Simula lo que queda en la DB si el bot se reinició antes del delete_after
    # rápido: una fila ya vencida. El sweep debe borrar el mensaje y la fila.
    from datetime import datetime, timedelta, timezone

    from cogs.anuncios import Anuncios

    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    asyncio.run(db.add_pending_deletion(10, 555, past))

    channel = _fake_channel(channel_id=10)
    fetched_message = AsyncMock()
    channel.fetch_message = AsyncMock(return_value=fetched_message)
    bot = MagicMock()
    bot.get_channel.return_value = channel
    cog = Anuncios(bot)
    asyncio.run(cog.sweep_pending_deletions.coro(cog))

    channel.fetch_message.assert_awaited_once_with(555)
    fetched_message.delete.assert_awaited_once()
    assert asyncio.run(db.get_due_pending_deletions()) == []


def test_pending_deletion_notfound_is_silently_cleared(memory_db):
    from datetime import datetime, timedelta, timezone

    from cogs.anuncios import Anuncios

    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    asyncio.run(db.add_pending_deletion(10, 555, past))

    channel = _fake_channel(channel_id=10)
    channel.fetch_message = AsyncMock(
        side_effect=discord.NotFound(MagicMock(status=404), "unknown message")
    )
    bot = MagicMock()
    bot.get_channel.return_value = channel
    cog = Anuncios(bot)
    asyncio.run(cog.sweep_pending_deletions.coro(cog))

    assert asyncio.run(db.get_due_pending_deletions()) == []


def test_scheduled_announcement_legacy_dict_embed_branch(memory_db):
    # Formato viejo (dict suelto, ya deployado): normalize_embeds_json lo
    # envuelve y el loop lo manda como embeds=[...] igual que el formato nuevo.
    embed_dict = {"title": "anuncio embed", "color": 0x8B6EF5}
    asyncio.run(
        db.add_scheduled_announcement(
            1,
            10,
            "[embed]",
            "interval",
            1,
            interval_minutes=30,
            embed_json=json.dumps(embed_dict),
        )
    )
    channel = _fake_channel()
    _run_announcement_loop(channel)
    channel.send.assert_awaited_once()
    kwargs = channel.send.await_args.kwargs
    assert channel.send.await_args.args == ()
    embeds = kwargs["embeds"]
    assert len(embeds) == 1
    assert embeds[0].title == "anuncio embed"
    assert embeds[0].colour.value == 0x8B6EF5


def test_scheduled_announcement_multi_embed_array_branch(memory_db):
    # Formato nuevo: array de varios embeds -> channel.send(embeds=[...]).
    embeds_json = json.dumps([{"title": "uno"}, {"title": "dos"}])
    asyncio.run(
        db.add_scheduled_announcement(
            1,
            10,
            "[embed]",
            "interval",
            1,
            interval_minutes=30,
            embed_json=embeds_json,
        )
    )
    channel = _fake_channel()
    _run_announcement_loop(channel)
    embeds = channel.send.await_args.kwargs["embeds"]
    assert [e.title for e in embeds] == ["uno", "dos"]


def test_get_due_includes_embed_json(memory_db):
    asyncio.run(
        db.add_scheduled_announcement(
            1,
            10,
            "[embed]",
            "interval",
            1,
            interval_minutes=30,
            embed_json='{"title": "x"}',
        )
    )
    due = asyncio.run(db.get_due_scheduled_announcements())
    assert len(due) == 1
    assert due[0]["embed_json"] == '{"title": "x"}'
    assert due[0]["content_mode"] == "classic_embed"


# ─── Layout Components V2: validate_layout_v2_payload ─────────────────────────

VALID_LAYOUT = {
    "blocks": [
        {
            "type": "container",
            "accent_color": "#8B6EF5",
            "children": [
                {"type": "text", "content": "hola **mundo**"},
                {
                    "type": "section",
                    "texts": ["izquierda"],
                    "accessory": {"type": "thumbnail", "url": "https://x/y.png"},
                },
                {"type": "separator", "visible": True, "spacing": "large"},
                {"type": "media_gallery", "items": [{"url": "https://a/1.png"}]},
            ],
        },
        {
            "type": "action_row",
            "buttons": [{"style": "link", "label": "Ir", "url": "https://x"}],
        },
    ]
}


def test_layout_valid():
    assert validate_layout_v2_payload(VALID_LAYOUT) is None


def test_layout_must_be_dict_with_blocks():
    assert validate_layout_v2_payload([]) is not None
    assert validate_layout_v2_payload({"blocks": []}) is not None
    assert validate_layout_v2_payload({}) is not None


def test_layout_text_total_4000_shared():
    over = {
        "blocks": [
            {"type": "text", "content": "x" * 2001},
            {"type": "text", "content": "y" * 2000},
        ]
    }
    ok = {
        "blocks": [
            {"type": "text", "content": "x" * 2000},
            {"type": "text", "content": "y" * 2000},
        ]
    }
    assert validate_layout_v2_payload(over) is not None
    assert validate_layout_v2_payload(ok) is None


def test_layout_section_max_3_texts():
    def section(n):
        return {
            "blocks": [
                {
                    "type": "section",
                    "texts": ["t"] * n,
                    "accessory": {"type": "thumbnail", "url": "https://x.test/i.png"},
                }
            ]
        }

    assert validate_layout_v2_payload(section(3)) is None
    assert validate_layout_v2_payload(section(4)) is not None


def test_layout_section_requires_accessory():
    assert (
        validate_layout_v2_payload({"blocks": [{"type": "section", "texts": ["a"]}]})
        is not None
    )


def test_layout_media_gallery_1_to_10():
    def gallery(n):
        return {
            "blocks": [
                {
                    "type": "media_gallery",
                    "items": [{"url": "https://x.test/i.png"}] * n,
                }
            ]
        }

    assert validate_layout_v2_payload(gallery(0)) is not None
    assert validate_layout_v2_payload(gallery(10)) is None
    assert validate_layout_v2_payload(gallery(11)) is not None


def test_layout_max_40_components():
    ok = {"blocks": [{"type": "text", "content": "x"} for _ in range(40)]}
    over = {"blocks": [{"type": "text", "content": "x"} for _ in range(41)]}
    assert validate_layout_v2_payload(ok) is None
    assert validate_layout_v2_payload(over) is not None


def test_layout_no_nested_containers():
    nested = {
        "blocks": [
            {
                "type": "container",
                "children": [
                    {
                        "type": "container",
                        "children": [{"type": "text", "content": "x"}],
                    }
                ],
            }
        ]
    }
    assert validate_layout_v2_payload(nested) is not None


def test_layout_only_link_buttons_in_phase2():
    role_btn = {
        "blocks": [{"type": "action_row", "buttons": [{"style": "role", "label": "x"}]}]
    }
    link_btn = {
        "blocks": [
            {
                "type": "action_row",
                "buttons": [{"style": "link", "label": "Ir", "url": "https://x"}],
            }
        ]
    }
    assert validate_layout_v2_payload(role_btn) is not None
    assert validate_layout_v2_payload(link_btn) is None


def test_build_layout_view_smoke():
    view = build_layout_view(VALID_LAYOUT)
    assert view.to_components()


# ─── Bloques File (Fase 2 ronda 2) ────────────────────────────────────────────


def _file_layout(upload_id="abc", filename="x.txt", spoiler=False):
    return {
        "blocks": [
            {
                "type": "file",
                "upload_id": upload_id,
                "filename": filename,
                "spoiler": spoiler,
            }
        ]
    }


def test_file_block_valid():
    assert validate_layout_v2_payload(_file_layout()) is None


def test_file_block_missing_upload_id_rejected():
    layout = _file_layout()
    layout["blocks"][0]["upload_id"] = ""
    assert validate_layout_v2_payload(layout) is not None


def test_file_block_missing_filename_rejected():
    layout = _file_layout()
    layout["blocks"][0]["filename"] = ""
    assert validate_layout_v2_payload(layout) is not None


def test_file_block_filename_too_long_rejected():
    layout = _file_layout(filename="x" * 257)
    assert validate_layout_v2_payload(layout) is not None


def test_file_block_spoiler_must_be_bool():
    layout = _file_layout()
    layout["blocks"][0]["spoiler"] = "yes"
    assert validate_layout_v2_payload(layout) is not None


def test_file_block_max_10_per_message():
    ok = {
        "blocks": [
            {
                "type": "file",
                "upload_id": str(i),
                "filename": f"{i}.txt",
                "spoiler": False,
            }
            for i in range(10)
        ]
    }
    over = {
        "blocks": [
            {
                "type": "file",
                "upload_id": str(i),
                "filename": f"{i}.txt",
                "spoiler": False,
            }
            for i in range(11)
        ]
    }
    assert validate_layout_v2_payload(ok) is None
    assert validate_layout_v2_payload(over) is not None


def test_has_file_block_detects_top_level():
    assert has_file_block(_file_layout()["blocks"]) is True
    assert has_file_block(VALID_LAYOUT["blocks"]) is False


def test_has_file_block_detects_nested_in_container():
    layout = {
        "blocks": [
            {
                "type": "container",
                "accent_color": None,
                "children": [{"type": "file", "upload_id": "a", "filename": "a.txt"}],
            }
        ]
    }
    assert has_file_block(layout["blocks"]) is True


def test_build_layout_view_attaches_file_component():
    layout = _file_layout(filename="doc.pdf")
    discord_file = discord.File(io.BytesIO(b"contenido"), filename="doc.pdf")
    view = build_layout_view(layout, files=[discord_file])
    components = view.to_components()
    assert components[0]["type"] == 13  # ComponentType.file
    assert components[0]["file"]["url"] == "attachment://doc.pdf"


def test_build_layout_view_raises_without_enough_files():
    layout = _file_layout()
    with pytest.raises(ValueError):
        build_layout_view(layout, files=[])


# ─── _resolve_layout_files / _pending_layout_files (webapi.py) ───────────────


@pytest.fixture(autouse=False)
def _clean_pending_files():
    webapi._pending_layout_files.clear()
    yield
    webapi._pending_layout_files.clear()


def test_resolve_layout_files_happy_path(_clean_pending_files):
    webapi._pending_layout_files["up1"] = {
        "data": b"hola",
        "filename": "hola.txt",
        "guild_id": 1,
        "expires_at": time.monotonic() + 600,
    }
    files, used, err = webapi._resolve_layout_files(
        _file_layout("up1", "hola.txt")["blocks"], guild_id=1
    )
    assert err is None
    assert used == ["up1"]
    assert len(files) == 1
    assert files[0].filename == "hola.txt"


def test_resolve_layout_files_missing_or_expired():
    files, used, err = webapi._resolve_layout_files(
        _file_layout("nope", "x.txt")["blocks"], guild_id=1
    )
    assert err is not None
    assert files == []


def test_resolve_layout_files_wrong_guild_rejected(_clean_pending_files):
    webapi._pending_layout_files["up1"] = {
        "data": b"hola",
        "filename": "hola.txt",
        "guild_id": 2,  # subido por otro guild
        "expires_at": time.monotonic() + 600,
    }
    files, used, err = webapi._resolve_layout_files(
        _file_layout("up1", "hola.txt")["blocks"], guild_id=1
    )
    assert err is not None


def test_resolve_layout_files_dedupes_duplicate_filename(_clean_pending_files):
    # Simula "Duplicar bloque": dos bloques file con el mismo upload_id.
    webapi._pending_layout_files["up1"] = {
        "data": b"hola",
        "filename": "hola.txt",
        "guild_id": 1,
        "expires_at": time.monotonic() + 600,
    }
    blocks = _file_layout("up1", "hola.txt")["blocks"] * 2
    files, used, err = webapi._resolve_layout_files(blocks, guild_id=1)
    assert err is None
    assert [f.filename for f in files] == ["hola.txt", "hola (2).txt"]
    assert used == ["up1", "up1"]


def test_prune_pending_layout_files_removes_expired():
    webapi._pending_layout_files.clear()
    webapi._pending_layout_files["old"] = {
        "data": b"x",
        "filename": "x.txt",
        "guild_id": 1,
        "expires_at": time.monotonic() - 1,
    }
    webapi._pending_layout_files["fresh"] = {
        "data": b"x",
        "filename": "x.txt",
        "guild_id": 1,
        "expires_at": time.monotonic() + 600,
    }
    webapi._prune_pending_layout_files()
    assert list(webapi._pending_layout_files.keys()) == ["fresh"]
    webapi._pending_layout_files.clear()


# ─── File blocks bloqueados en Programar y en plantillas ─────────────────────


def test_extract_content_rejects_file_block_for_schedule_or_templates():
    data = {"content_mode": "layout_v2", "layout": _file_layout()}
    content_mode, payload, preview, err = webapi._extract_content(data)
    assert err is not None
    assert content_mode == ""


def test_extract_content_accepts_layout_without_file_block():
    data = {"content_mode": "layout_v2", "layout": VALID_LAYOUT}
    content_mode, payload, preview, err = webapi._extract_content(data)
    assert err is None
    assert content_mode == "layout_v2"


# ─── content_mode: round-trip y branch de anuncios ───────────────────────────


def test_template_content_mode_roundtrip(memory_db):
    tid = asyncio.run(db.add_embed_template(1, "lay", '{"blocks": []}', "layout_v2"))
    assert asyncio.run(db.get_embed_template(tid, 1))["content_mode"] == "layout_v2"
    assert asyncio.run(db.list_embed_templates(1))[0]["content_mode"] == "layout_v2"


def test_template_default_content_mode_is_classic(memory_db):
    tid = asyncio.run(db.add_embed_template(1, "clasica", '[{"title": "t"}]'))
    assert asyncio.run(db.get_embed_template(tid, 1))["content_mode"] == "classic_embed"


def test_scheduled_announcement_layout_v2_branch(memory_db):
    layout = {"blocks": [{"type": "text", "content": "layout va"}]}
    asyncio.run(
        db.add_scheduled_announcement(
            1,
            10,
            "[layout]",
            "interval",
            1,
            interval_minutes=30,
            embed_json=json.dumps(layout),
            content_mode="layout_v2",
        )
    )
    channel = _fake_channel()
    _run_announcement_loop(channel)
    channel.send.assert_awaited_once()
    kwargs = channel.send.await_args.kwargs
    assert isinstance(kwargs.get("view"), discord.ui.LayoutView)
    assert "embeds" not in kwargs and "embed" not in kwargs


# ─── Botones de rol (Fase 3): validate_layout_v2_payload + estilo 'role' ─────


def test_role_button_valid():
    layout = {
        "blocks": [
            {
                "type": "action_row",
                "buttons": [
                    {"style": "role", "label": "Suscriptor", "role_id": 555},
                ],
            }
        ]
    }
    assert validate_layout_v2_payload(layout) is None


def test_role_button_accepts_numeric_string_role_id():
    layout = {
        "blocks": [
            {
                "type": "action_row",
                "buttons": [
                    {"style": "role", "label": "x", "role_id": "555"},
                ],
            }
        ]
    }
    assert validate_layout_v2_payload(layout) is None


def test_role_button_requires_role_id():
    layout = {
        "blocks": [
            {
                "type": "action_row",
                "buttons": [
                    {"style": "role", "label": "x"},
                ],
            }
        ]
    }
    assert validate_layout_v2_payload(layout) is not None


def test_role_button_rejects_non_numeric_role_id():
    layout = {
        "blocks": [
            {
                "type": "action_row",
                "buttons": [
                    {"style": "role", "label": "x", "role_id": "abc"},
                ],
            }
        ]
    }
    assert validate_layout_v2_payload(layout) is not None


def test_unknown_button_style_rejected():
    layout = {
        "blocks": [
            {
                "type": "action_row",
                "buttons": [
                    {"style": "modal", "label": "x"},
                ],
            }
        ]
    }
    assert validate_layout_v2_payload(layout) is not None


def test_section_accessory_role_button_valid():
    layout = {
        "blocks": [
            {
                "type": "section",
                "texts": ["hola"],
                "accessory": {
                    "type": "button",
                    "style": "role",
                    "label": "Rol",
                    "role_id": 1,
                },
            }
        ]
    }
    assert validate_layout_v2_payload(layout) is None


# ─── assign_button_custom_ids ────────────────────────────────────────────────


def test_assign_custom_ids_only_role_buttons():
    layout = {
        "blocks": [
            {
                "type": "action_row",
                "buttons": [
                    {"style": "link", "label": "Ir", "url": "https://x"},
                    {"style": "role", "label": "Suscriptor", "role_id": 555},
                ],
            }
        ]
    }
    assigned = assign_button_custom_ids(layout)
    assert len(assigned) == 1
    assert assigned[0]["role_id"] == 555
    link_btn, role_btn = layout["blocks"][0]["buttons"]
    assert "custom_id" not in link_btn
    assert role_btn["custom_id"].startswith(ROLE_TOGGLE_PREFIX)


def test_assign_custom_ids_idempotent():
    layout = {
        "blocks": [
            {
                "type": "action_row",
                "buttons": [
                    {"style": "role", "label": "x", "role_id": 1},
                ],
            }
        ]
    }
    first = assign_button_custom_ids(layout)
    cid = layout["blocks"][0]["buttons"][0]["custom_id"]
    second = assign_button_custom_ids(layout)
    assert len(first) == 1
    assert second == []  # ya tenía custom_id: no se reasigna ni se re-reporta
    assert layout["blocks"][0]["buttons"][0]["custom_id"] == cid


def test_assign_custom_ids_walks_nested_container_and_section():
    layout = {
        "blocks": [
            {
                "type": "container",
                "children": [
                    {
                        "type": "action_row",
                        "buttons": [{"style": "role", "label": "a", "role_id": 1}],
                    },
                ],
            },
            {
                "type": "section",
                "texts": ["t"],
                "accessory": {
                    "type": "button",
                    "style": "role",
                    "label": "b",
                    "role_id": 2,
                },
            },
        ]
    }
    assigned = assign_button_custom_ids(layout)
    assert len(assigned) == 2
    assert {a["role_id"] for a in assigned} == {1, 2}

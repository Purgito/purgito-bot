"""Tests exhaustivos del formato de salida de /refeed y /refeed_channels.

Verifica:
1. /refeed_channels produce una sola salida final visible (no hay doble envío).
2. El mensaje final incluye mensajes aprendidos.
3. Incluye GIFs cuando gifs_saved > 0 ("y guardé X GIFs" / "and saved X GIFs").
4. No menciona GIFs cuando gifs_saved == 0.
5. Pluralización natural en canal/canales y GIF/GIFs.
6. El flujo parcial mantiene su información ("Listo por ahora.", aviso de continuar).
7. El flujo con permisos mantiene su información (aviso de canal sin permisos).
8. Fallback a report_channel cuando progress_msg es None o falla su edición.
9. /refeed no queda afectado y maneja plurales de GIFs y estados correctamente.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

import cogs.chat as chat_mod
import tasks
from cogs.chat import Chat


class _FakeProgressMessage:
    def __init__(self, mid=1):
        self.id = mid
        self.edits: list[str] = []

    async def edit(self, content=None, **kw):
        self.edits.append(content)


def _make_fake_channel(cid=10, name="general", message=None) -> MagicMock:
    ch = MagicMock(spec=discord.TextChannel)
    ch.id = cid
    ch.name = name
    ch.sent = []

    async def _fetch(mid):
        return message

    async def _send(content=None, **kw):
        ch.sent.append(content)

    ch.fetch_message = _fetch
    ch.send = _send
    ch.permissions_for.return_value = SimpleNamespace(
        read_messages=True, read_message_history=True
    )
    return ch


class _FakeInteraction:
    def __init__(self, guild_id=1, locale="es", mid=1):
        self.guild = SimpleNamespace(id=guild_id)
        self.progress_message = _FakeProgressMessage(mid)
        self.channel = _make_fake_channel(10, "general", self.progress_message)
        self.user = SimpleNamespace(id=99)
        self.sent_messages: list[str] = []
        self.followup_sent: list[str] = []

        async def send_message(content=None, **kw):
            self.sent_messages.append(content)

        async def original_response():
            await asyncio.sleep(0)
            return self.progress_message

        async def followup_send(content=None, **kw):
            self.followup_sent.append(content)

        async def defer(thinking=False, **kw):
            pass

        self.response = SimpleNamespace(
            send_message=send_message,
            defer=defer,
        )
        self.original_response = original_response
        self.followup = SimpleNamespace(send=followup_send)


def _fake_text_channel(channel_id: int, name: str, can_read: bool = True) -> MagicMock:
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.name = name
    channel.permissions_for.return_value = SimpleNamespace(
        read_messages=can_read, read_message_history=can_read
    )
    return channel


def _fake_guild(guild_id: int, channels: list) -> SimpleNamespace:
    by_id = {c.id: c for c in channels}
    return SimpleNamespace(
        id=guild_id, me=SimpleNamespace(), get_channel=lambda cid: by_id.get(cid)
    )


@pytest.fixture(autouse=True)
def _clean_tasks_and_guards(monkeypatch):
    tm = tasks.get_task_manager()
    tm._tasks.clear()
    tm._locks.clear()
    tm._expires_at.clear()
    chat_mod._refeeding_channels.clear()

    async def _default_locale(gid):
        return "es"

    async def _default_not_ignored(gid, cid):
        return False

    async def _default_allowed(gid, cid):
        return True

    monkeypatch.setattr(chat_mod.i18n, "guild_locale", _default_locale)
    monkeypatch.setattr(chat_mod, "is_channel_ignored", _default_not_ignored)
    monkeypatch.setattr(chat_mod, "is_corpus_allowed", _default_allowed)
    yield
    chat_mod._refeeding_channels.clear()


# ─── 1. /refeed_channels: Una sola salida visible (sin doble envío) ───────────


def test_refeed_channels_single_output_edited_no_duplicate_send(monkeypatch):
    """Verifica que /refeed_channels envía UN mensaje inicial y luego lo edita,
    sin enviar un segundo mensaje idéntico al canal."""
    chat = Chat(SimpleNamespace())
    monkeypatch.setattr(chat_mod, "has_admin_permission", lambda inter: True)

    async def fake_list_channels(gid):
        return [101]

    monkeypatch.setattr(chat_mod, "list_corpus_channels", fake_list_channels)

    ch1 = _fake_text_channel(101, "general")
    guild = _fake_guild(1, [ch1])

    async def fake_refeed_channel(gid, channel, max_msgs):
        return {
            "saved": 81,
            "gifs_saved": 4,
            "backfill_complete": True,
            "was_incremental": False,
            "forbidden": False,
        }

    monkeypatch.setattr(chat, "_refeed_channel", fake_refeed_channel)

    inter = _FakeInteraction(guild_id=1, locale="es")
    inter.guild = guild

    captured_tasks = []
    real_create_task = asyncio.create_task

    def capture(coro, *a, **k):
        t = real_create_task(coro, *a, **k)
        captured_tasks.append(t)
        return t

    monkeypatch.setattr(chat_mod.asyncio, "create_task", capture)

    async def run():
        await chat.refeed_channels.callback(chat, inter)
        assert len(captured_tasks) == 1
        await captured_tasks[0]

    asyncio.run(run())

    # 1. Envió mensaje inicial
    assert inter.sent_messages == ["Empezando a leer el historial de los canales…"]
    # 2. El canal NO recibió llamadas a send() (NO hubo mensaje duplicado)
    assert inter.channel.sent == []
    # 3. El mensaje de progreso fue editado con el resumen final
    assert len(inter.progress_message.edits) >= 1
    final_edit = inter.progress_message.edits[-1]
    assert "Listo." in final_edit
    assert "Aprendí de 81 mensajes en 1 canal y guardé 4 GIFs." in final_edit
    assert "Ya puedes probar `/generar` o mencionarme." in final_edit


# ─── 2. Estructura y formato del mensaje final con GIFs y plurales ─────────────


def test_refeed_channels_summary_complete_with_gifs_multiple_channels(monkeypatch):
    chat = Chat(SimpleNamespace())
    ch1 = _fake_text_channel(101, "general")
    ch2 = _fake_text_channel(102, "charla")
    ch3 = _fake_text_channel(103, "memes")
    guild = _fake_guild(1, [ch1, ch2, ch3])

    async def fake_list_channels(gid):
        return [101, 102, 103]

    monkeypatch.setattr(chat_mod, "list_corpus_channels", fake_list_channels)

    results = {
        101: {"saved": 30, "gifs_saved": 2, "backfill_complete": True, "was_incremental": False, "forbidden": False},
        102: {"saved": 31, "gifs_saved": 1, "backfill_complete": True, "was_incremental": False, "forbidden": False},
        103: {"saved": 20, "gifs_saved": 1, "backfill_complete": True, "was_incremental": False, "forbidden": False},
    }

    async def fake_refeed_channel(gid, channel, max_msgs):
        return results[channel.id]

    monkeypatch.setattr(chat, "_refeed_channel", fake_refeed_channel)

    # Español
    progress_msg_es = _FakeProgressMessage()
    asyncio.run(chat._refeed_guild(guild, progress_msg_es, None))
    expected_es = (
        "Listo.\n\n"
        "Aprendí de 81 mensajes en 3 canales y guardé 4 GIFs.\n\n"
        "Ya puedes probar `/generar` o mencionarme."
    )
    assert progress_msg_es.edits[-1] == expected_es

    # Inglés
    async def fake_locale_en(gid):
        return "en"

    monkeypatch.setattr(chat_mod.i18n, "guild_locale", fake_locale_en)
    progress_msg_en = _FakeProgressMessage()
    asyncio.run(chat._refeed_guild(guild, progress_msg_en, None))
    expected_en = (
        "Done.\n\n"
        "Learned from 81 messages across 3 channels and saved 4 GIFs.\n\n"
        "You can now try `/generar` or mention me."
    )
    assert progress_msg_en.edits[-1] == expected_en


# ─── 3. Sin GIFs y un solo canal ──────────────────────────────────────────────


def test_refeed_channels_summary_without_gifs_single_channel(monkeypatch):
    chat = Chat(SimpleNamespace())
    ch1 = _fake_text_channel(101, "general")
    guild = _fake_guild(1, [ch1])

    async def fake_list_channels(gid):
        return [101]

    monkeypatch.setattr(chat_mod, "list_corpus_channels", fake_list_channels)

    async def fake_refeed_channel(gid, channel, max_msgs):
        return {
            "saved": 81,
            "gifs_saved": 0,
            "backfill_complete": True,
            "was_incremental": False,
            "forbidden": False,
        }

    monkeypatch.setattr(chat, "_refeed_channel", fake_refeed_channel)

    # Español
    progress_msg_es = _FakeProgressMessage()
    asyncio.run(chat._refeed_guild(guild, progress_msg_es, None))
    expected_es = (
        "Listo.\n\n"
        "Aprendí de 81 mensajes en 1 canal.\n\n"
        "Ya puedes probar `/generar` o mencionarme."
    )
    assert progress_msg_es.edits[-1] == expected_es
    assert "GIF" not in progress_msg_es.edits[-1]

    # Inglés
    async def fake_locale_en(gid):
        return "en"

    monkeypatch.setattr(chat_mod.i18n, "guild_locale", fake_locale_en)
    progress_msg_en = _FakeProgressMessage()
    asyncio.run(chat._refeed_guild(guild, progress_msg_en, None))
    expected_en = (
        "Done.\n\n"
        "Learned from 81 messages across 1 channel.\n\n"
        "You can now try `/generar` or mention me."
    )
    assert progress_msg_en.edits[-1] == expected_en
    assert "GIF" not in progress_msg_en.edits[-1]


# ─── 4. Singular de GIF (1 GIF) ───────────────────────────────────────────────


def test_refeed_channels_summary_single_gif_singular(monkeypatch):
    chat = Chat(SimpleNamespace())
    ch1 = _fake_text_channel(101, "general")
    guild = _fake_guild(1, [ch1])

    async def fake_list_channels(gid):
        return [101]

    monkeypatch.setattr(chat_mod, "list_corpus_channels", fake_list_channels)

    async def fake_refeed_channel(gid, channel, max_msgs):
        return {
            "saved": 10,
            "gifs_saved": 1,
            "backfill_complete": True,
            "was_incremental": False,
            "forbidden": False,
        }

    monkeypatch.setattr(chat, "_refeed_channel", fake_refeed_channel)

    progress_msg_es = _FakeProgressMessage()
    asyncio.run(chat._refeed_guild(guild, progress_msg_es, None))
    assert "Aprendí de 10 mensajes en 1 canal y guardé 1 GIF." in progress_msg_es.edits[-1]

    async def fake_locale_en(gid):
        return "en"

    monkeypatch.setattr(chat_mod.i18n, "guild_locale", fake_locale_en)
    progress_msg_en = _FakeProgressMessage()
    asyncio.run(chat._refeed_guild(guild, progress_msg_en, None))
    assert "Learned from 10 messages across 1 channel and saved 1 GIF." in progress_msg_en.edits[-1]


# ─── 5. Estado parcial (límite de mensajes alcanzado) ─────────────────────────


def test_refeed_channels_summary_partial(monkeypatch):
    chat = Chat(SimpleNamespace())
    ch1 = _fake_text_channel(101, "general")
    ch2 = _fake_text_channel(102, "charla")
    ch3 = _fake_text_channel(103, "memes")
    guild = _fake_guild(1, [ch1, ch2, ch3])

    async def fake_list_channels(gid):
        return [101, 102, 103]

    monkeypatch.setattr(chat_mod, "list_corpus_channels", fake_list_channels)

    async def fake_refeed_channel(gid, channel, max_msgs):
        return {
            "saved": 1733 if channel.id == 101 else 1733 if channel.id == 102 else 1734,
            "gifs_saved": 0,
            "backfill_complete": False,  # Parcial
            "was_incremental": False,
            "forbidden": False,
        }

    monkeypatch.setattr(chat, "_refeed_channel", fake_refeed_channel)

    progress_msg_es = _FakeProgressMessage()
    asyncio.run(chat._refeed_guild(guild, progress_msg_es, None))
    expected_es = (
        "Listo por ahora.\n\n"
        "Aprendí de 5,200 mensajes en 3 canales.\n\n"
        "Algunos canales todavía tienen más historial por leer. Puedes ejecutar `/refeed_channels` de nuevo para continuar."
    )
    assert progress_msg_es.edits[-1] == expected_es

    async def fake_locale_en(gid):
        return "en"

    monkeypatch.setattr(chat_mod.i18n, "guild_locale", fake_locale_en)
    progress_msg_en = _FakeProgressMessage()
    asyncio.run(chat._refeed_guild(guild, progress_msg_en, None))
    expected_en = (
        "Done for now.\n\n"
        "Learned from 5,200 messages across 3 channels.\n\n"
        "Some channels still have more history to read. You can run `/refeed_channels` again to continue."
    )
    assert progress_msg_en.edits[-1] == expected_en


# ─── 6. Estado con permisos insuficientes en algunos canales ───────────────────


def test_refeed_channels_summary_with_permissions_issues(monkeypatch):
    chat = Chat(SimpleNamespace())
    ch1 = _fake_text_channel(101, "general", can_read=True)
    ch2 = _fake_text_channel(102, "privado", can_read=False)
    guild = _fake_guild(1, [ch1, ch2])

    async def fake_list_channels(gid):
        return [101, 102]

    monkeypatch.setattr(chat_mod, "list_corpus_channels", fake_list_channels)

    async def fake_refeed_channel(gid, channel, max_msgs):
        return {
            "saved": 81,
            "gifs_saved": 0,
            "backfill_complete": True,
            "was_incremental": False,
            "forbidden": False,
        }

    monkeypatch.setattr(chat, "_refeed_channel", fake_refeed_channel)

    progress_msg_es = _FakeProgressMessage()
    asyncio.run(chat._refeed_guild(guild, progress_msg_es, None))
    expected_es = (
        "Listo.\n\n"
        "Aprendí de 81 mensajes en 1 canal.\n\n"
        "No pude leer #privado porque Purgito no tiene permisos para ver su historial.\n\n"
        "Ya puedes probar `/generar` o mencionarme."
    )
    assert progress_msg_es.edits[-1] == expected_es

    async def fake_locale_en(gid):
        return "en"

    monkeypatch.setattr(chat_mod.i18n, "guild_locale", fake_locale_en)
    progress_msg_en = _FakeProgressMessage()
    asyncio.run(chat._refeed_guild(guild, progress_msg_en, None))
    expected_en = (
        "Done.\n\n"
        "Learned from 81 messages across 1 channel.\n\n"
        "I couldn't read #privado because Purgito does not have permission to view its history.\n\n"
        "You can now try `/generar` or mention me."
    )
    assert progress_msg_en.edits[-1] == expected_en


# ─── 7. Todos los canales sin permisos ─────────────────────────────────────────


def test_refeed_channels_summary_all_forbidden(monkeypatch):
    chat = Chat(SimpleNamespace())
    ch1 = _fake_text_channel(101, "general", can_read=False)
    guild = _fake_guild(1, [ch1])

    async def fake_list_channels(gid):
        return [101]

    monkeypatch.setattr(chat_mod, "list_corpus_channels", fake_list_channels)

    progress_msg_es = _FakeProgressMessage()
    asyncio.run(chat._refeed_guild(guild, progress_msg_es, None))
    expected_es = (
        "Terminé con algunos problemas.\n\n"
        "No pude leer #general porque Purgito no tiene permisos para ver su historial.\n\n"
        "Puedes revisar los permisos de esos canales e intentarlo de nuevo."
    )
    assert progress_msg_es.edits[-1] == expected_es


# ─── 8. Fallback a report_channel si progress_msg es None o falla edición ───────


def test_refeed_channels_fallback_to_report_channel_if_progress_msg_none(monkeypatch):
    chat = Chat(SimpleNamespace())
    ch1 = _fake_text_channel(101, "general")
    guild = _fake_guild(1, [ch1])

    async def fake_list_channels(gid):
        return [101]

    monkeypatch.setattr(chat_mod, "list_corpus_channels", fake_list_channels)

    async def fake_refeed_channel(gid, channel, max_msgs):
        return {
            "saved": 50,
            "gifs_saved": 0,
            "backfill_complete": True,
            "was_incremental": False,
            "forbidden": False,
        }

    monkeypatch.setattr(chat, "_refeed_channel", fake_refeed_channel)

    report_ch = _make_fake_channel(10, "general")
    asyncio.run(chat._refeed_guild(guild, None, report_ch))

    # progress_msg fue None -> report_ch.send se llamó exactamente 1 vez
    assert len(report_ch.sent) == 1
    assert "Aprendí de 50 mensajes en 1 canal." in report_ch.sent[0]


def test_refeed_channels_fallback_to_report_channel_if_edit_fails(monkeypatch):
    chat = Chat(SimpleNamespace())
    ch1 = _fake_text_channel(101, "general")
    guild = _fake_guild(1, [ch1])

    async def fake_list_channels(gid):
        return [101]

    monkeypatch.setattr(chat_mod, "list_corpus_channels", fake_list_channels)

    async def fake_refeed_channel(gid, channel, max_msgs):
        return {
            "saved": 50,
            "gifs_saved": 0,
            "backfill_complete": True,
            "was_incremental": False,
            "forbidden": False,
        }

    monkeypatch.setattr(chat, "_refeed_channel", fake_refeed_channel)

    broken_progress_msg = MagicMock()
    broken_progress_msg.edit = AsyncMock(side_effect=RuntimeError("message deleted"))

    report_ch = _make_fake_channel(10, "general")
    asyncio.run(chat._refeed_guild(guild, broken_progress_msg, report_ch))

    # Edición falló -> fallback a report_ch.send
    assert len(report_ch.sent) == 1
    assert "Aprendí de 50 mensajes en 1 canal." in report_ch.sent[0]


# ─── 9. Comando /refeed (canal único): no afectado y maneja gifs_suffix ────────


def test_refeed_single_channel_complete_incremental_partial(monkeypatch):
    chat = Chat(SimpleNamespace())
    monkeypatch.setattr(chat_mod, "has_admin_permission", lambda inter: True)

    async def fake_locale(gid):
        return "es"

    monkeypatch.setattr(chat_mod.i18n, "guild_locale", fake_locale)

    # 1. Complete con 0 gifs
    async def fake_refeed_1(gid, ch, max_m):
        return {"saved": 81, "gifs_saved": 0, "backfill_complete": True, "was_incremental": False, "forbidden": False}

    monkeypatch.setattr(chat, "_refeed_channel", fake_refeed_1)
    inter1 = _FakeInteraction()
    asyncio.run(chat.refeed.callback(chat, inter1))
    assert inter1.followup_sent == ["Historial completado: 81 mensajes aprendidos."]

    # 2. Complete con 1 gif (singular)
    async def fake_refeed_2(gid, ch, max_m):
        return {"saved": 81, "gifs_saved": 1, "backfill_complete": True, "was_incremental": False, "forbidden": False}

    monkeypatch.setattr(chat, "_refeed_channel", fake_refeed_2)
    inter2 = _FakeInteraction()
    asyncio.run(chat.refeed.callback(chat, inter2))
    assert inter2.followup_sent == ["Historial completado: 81 mensajes aprendidos y 1 GIF nuevo."]

    # 3. Complete con 4 gifs (plural)
    async def fake_refeed_3(gid, ch, max_m):
        return {"saved": 81, "gifs_saved": 4, "backfill_complete": True, "was_incremental": False, "forbidden": False}

    monkeypatch.setattr(chat, "_refeed_channel", fake_refeed_3)
    inter3 = _FakeInteraction()
    asyncio.run(chat.refeed.callback(chat, inter3))
    assert inter3.followup_sent == ["Historial completado: 81 mensajes aprendidos y 4 GIFs nuevos."]

    # 4. Incremental con 2 gifs
    async def fake_refeed_4(gid, ch, max_m):
        return {"saved": 5, "gifs_saved": 2, "backfill_complete": True, "was_incremental": True, "forbidden": False}

    monkeypatch.setattr(chat, "_refeed_channel", fake_refeed_4)
    inter4 = _FakeInteraction()
    asyncio.run(chat.refeed.callback(chat, inter4))
    assert inter4.followup_sent == ["Este canal ya estaba al día: 5 mensajes nuevos aprendidos y 2 GIFs nuevos."]

    # 5. Parcial (límite alcanzado)
    async def fake_refeed_5(gid, ch, max_m):
        return {"saved": 80000, "gifs_saved": 0, "backfill_complete": False, "was_incremental": False, "forbidden": False}

    monkeypatch.setattr(chat, "_refeed_channel", fake_refeed_5)
    inter5 = _FakeInteraction()
    asyncio.run(chat.refeed.callback(chat, inter5))
    assert "Se aprendieron 80,000 mensajes." in inter5.followup_sent[0]
    assert "Límite de 80,000 mensajes alcanzado" in inter5.followup_sent[0]

    # 6. Forbidden
    async def fake_refeed_6(gid, ch, max_m):
        return {"saved": 0, "gifs_saved": 0, "backfill_complete": False, "was_incremental": False, "forbidden": True}

    monkeypatch.setattr(chat, "_refeed_channel", fake_refeed_6)
    inter6 = _FakeInteraction()
    asyncio.run(chat.refeed.callback(chat, inter6))
    assert inter6.followup_sent == ["Purgito no tiene permiso para ver el historial de este canal."]

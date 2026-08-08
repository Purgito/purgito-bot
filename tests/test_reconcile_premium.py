"""Tests de scripts/reconcile_premium.py.

De solo lectura: nunca debe escribir en la DB ni en Polar, solo reportar. El
cliente de Polar y la conexión SQLite son falsos/en memoria.
"""

import sqlite3
import sys
from types import SimpleNamespace

sys.path.insert(0, "scripts")
import reconcile_premium as rec  # noqa: E402


class _FakeSub:
    def __init__(self, id_, guild_id):
        self.id = id_
        self.metadata = {"guild_id": guild_id} if guild_id is not None else {}


class _FakeListResult:
    def __init__(self, items):
        self.items = items


class _FakeResponse:
    def __init__(self, items, next_response=None):
        self.result = _FakeListResult(items)
        self._next = next_response

    def next(self):
        return self._next


class _FakeSubscriptionsAPI:
    def __init__(self, response):
        self._response = response
        self.calls: list[dict] = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def _conn_with_premium(guild_ids: set[int]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE premium_guilds (guild_id INTEGER PRIMARY KEY, added_at TEXT, note TEXT)"
    )
    conn.executemany(
        "INSERT INTO premium_guilds (guild_id, added_at) VALUES (?, 'now')",
        [(g,) for g in guild_ids],
    )
    conn.commit()
    return conn


def test_sin_discrepancias_no_reporta_nada(capsys):
    response = _FakeResponse([_FakeSub("sub_1", "123")])
    client = SimpleNamespace(subscriptions=_FakeSubscriptionsAPI(response))
    conn = _conn_with_premium({123})

    result = rec.reconcile(client, conn)

    assert result["polar_only"] == {}
    assert result["local_only"] == set()
    assert "Bien." in capsys.readouterr().out


def test_activa_en_polar_pero_no_local_se_reporta(capsys):
    response = _FakeResponse([_FakeSub("sub_1", "123")])
    client = SimpleNamespace(subscriptions=_FakeSubscriptionsAPI(response))
    conn = _conn_with_premium(set())  # nada local

    result = rec.reconcile(client, conn)

    assert result["polar_only"] == {123: "sub_1"}
    out = capsys.readouterr().out
    assert "guild 123" in out
    assert "sub_1" in out


def test_local_pero_no_activa_en_polar_se_reporta(capsys):
    response = _FakeResponse([])  # nada activo en Polar
    client = SimpleNamespace(subscriptions=_FakeSubscriptionsAPI(response))
    conn = _conn_with_premium({456})

    result = rec.reconcile(client, conn)

    assert result["local_only"] == {456}
    assert "guild 456" in capsys.readouterr().out


def test_purgatory_guild_id_excluido_del_reporte(monkeypatch, capsys):
    """El guild home es siempre premium y nunca pasa por Polar a propósito
    (ver is_premium_guild en cogs/premium.py) -- no es una discrepancia real."""
    monkeypatch.setattr(rec.config, "PURGATORY_GUILD_ID", 999)
    response = _FakeResponse([])
    client = SimpleNamespace(subscriptions=_FakeSubscriptionsAPI(response))
    conn = _conn_with_premium({999})

    result = rec.reconcile(client, conn)

    assert result["local_only"] == set()


def test_pagina_siguiente_se_recorre_con_next(capsys):
    segunda_pagina = _FakeResponse([_FakeSub("sub_2", "789")])
    primera_pagina = _FakeResponse(
        [_FakeSub("sub_1", "123")], next_response=segunda_pagina
    )
    client = SimpleNamespace(subscriptions=_FakeSubscriptionsAPI(primera_pagina))
    conn = _conn_with_premium(set())

    result = rec.reconcile(client, conn)

    assert result["polar_only"] == {123: "sub_1", 789: "sub_2"}


def test_metadata_sin_guild_id_valido_se_avisa_y_se_saltea(capsys):
    response = _FakeResponse([_FakeSub("sub_1", "no-es-un-numero")])
    client = SimpleNamespace(subscriptions=_FakeSubscriptionsAPI(response))
    conn = _conn_with_premium(set())

    result = rec.reconcile(client, conn)

    assert result["polar_only"] == {}
    assert "AVISO" in capsys.readouterr().out


def test_filtra_por_los_product_id_configurados(monkeypatch):
    monkeypatch.setattr(rec.config, "POLAR_PRODUCT_ID_MONTHLY", "prod-monthly")
    monkeypatch.setattr(rec.config, "POLAR_PRODUCT_ID_ANNUAL", "prod-annual")
    response = _FakeResponse([])
    api = _FakeSubscriptionsAPI(response)
    client = SimpleNamespace(subscriptions=api)
    conn = _conn_with_premium(set())

    rec.reconcile(client, conn)

    assert api.calls[0]["product_id"] == ["prod-monthly", "prod-annual"]
    assert api.calls[0]["active"] is True

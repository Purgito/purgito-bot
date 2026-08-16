"""Tests de scripts/reconcile_premium.py.

reconcile() es de solo lectura: nunca escribe en la DB ni en Polar, solo
reporta. La única excepción es backfill_subscriptions(), gateada detrás de
--backfill-subscriptions y con su propio riesgo acotado (ver docstring del
módulo): nunca toca premium_guilds, solo agrega filas a premium_subscriptions
que todavía no existen. El cliente de Polar y la conexión SQLite son
falsos/en memoria.
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


class _FakeCustomer:
    def __init__(self, external_id):
        self.external_id = external_id


class _FakeFullSub:
    """Suscripción con todos los campos que backfill_subscriptions lee --
    _FakeSub de arriba solo tiene id/metadata, alcanza para los tests de
    reconcile() pero no para probar el mapeo completo de campos."""

    def __init__(self, **kw):
        self.id = kw.get("id", "sub-1")
        self.metadata = {"guild_id": kw.get("guild_id", "123")}
        self.customer_id = kw.get("customer_id", "cus_1")
        self.customer = _FakeCustomer(kw.get("purchaser_user_id", "42"))
        self.product_id = kw.get("product_id", "prod-monthly")
        self.status = kw.get("status", "active")
        self.current_period_start = kw.get("current_period_start")
        self.current_period_end = kw.get("current_period_end")
        self.trial_start = kw.get("trial_start")
        self.trial_end = kw.get("trial_end")
        self.cancel_at_period_end = kw.get("cancel_at_period_end", False)
        self.canceled_at = kw.get("canceled_at")


def _add_premium_subscriptions_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE premium_subscriptions (
            guild_id INTEGER PRIMARY KEY,
            subscription_id TEXT,
            customer_id TEXT,
            purchaser_user_id TEXT,
            product_id TEXT,
            status TEXT,
            current_period_start TEXT,
            current_period_end TEXT,
            trial_start TEXT,
            trial_end TEXT,
            cancel_at_period_end INTEGER,
            canceled_at TEXT,
            event_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.commit()


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


def test_is_premium_guild_permanent_guilds():
    from cogs.premium import is_premium_guild

    assert is_premium_guild(1434103563214393347) is True
    assert is_premium_guild(1521362322331795487) is True
    assert is_premium_guild(None) is False


def test_permanent_premium_guild_ids_excluido_del_reporte(capsys):
    response = _FakeResponse([])
    client = SimpleNamespace(subscriptions=_FakeSubscriptionsAPI(response))
    conn = _conn_with_premium({1521362322331795487})

    result = rec.reconcile(client, conn)
    assert result["local_only"] == set()


# ── backfill_subscriptions: nunca pisa una fila existente ──────────────────


def test_backfill_agrega_solo_los_guilds_que_faltan():
    conn = _conn_with_premium({123, 456})
    _add_premium_subscriptions_table(conn)
    # 123 ya tiene fila -- simula una escrita por un webhook real previo.
    conn.execute(
        "INSERT INTO premium_subscriptions (guild_id, subscription_id, updated_at) "
        "VALUES (123, 'sub-real-del-webhook', 'antes')"
    )
    conn.commit()

    polar_active = {
        123: _FakeSub("sub-que-polar-diria-ahora", "123"),
        456: _FakeSub("sub-456", "456"),
    }

    added = rec.backfill_subscriptions(conn, polar_active)

    assert added == [456]
    rows = dict(
        conn.execute("SELECT guild_id, subscription_id FROM premium_subscriptions")
    )
    assert rows[123] == "sub-real-del-webhook"  # INSERT OR IGNORE: no se pisó
    assert rows[456] == "sub-456"


def test_backfill_no_toca_premium_guilds():
    """El riesgo que la elección de diseño evita a propósito: backfillear
    datos de facturación nunca debe poder cambiar el acceso de nadie."""
    conn = _conn_with_premium({456})
    _add_premium_subscriptions_table(conn)

    rec.backfill_subscriptions(conn, {456: _FakeSub("sub-456", "456")})

    assert {r[0] for r in conn.execute("SELECT guild_id FROM premium_guilds")} == {456}


def test_backfill_mapea_todos_los_campos():
    conn = _conn_with_premium(set())
    _add_premium_subscriptions_table(conn)
    from datetime import datetime, timezone

    period_end = datetime(2026, 9, 1, tzinfo=timezone.utc)
    sub = _FakeFullSub(
        id="sub-789",
        guild_id="789",
        customer_id="cus_789",
        purchaser_user_id="99",
        product_id="prod-annual",
        status="active",
        current_period_end=period_end,
        cancel_at_period_end=True,
    )

    added = rec.backfill_subscriptions(conn, {789: sub})

    assert added == [789]
    row = conn.execute(
        "SELECT subscription_id, customer_id, purchaser_user_id, product_id, "
        "status, current_period_end, cancel_at_period_end, event_at "
        "FROM premium_subscriptions WHERE guild_id=789"
    ).fetchone()
    assert row == (
        "sub-789",
        "cus_789",
        "99",
        "prod-annual",
        "active",
        "2026-09-01T00:00:00+00:00",
        1,
        None,
    )


def test_backfill_sin_nada_pendiente_no_agrega_nada():
    conn = _conn_with_premium(set())
    _add_premium_subscriptions_table(conn)
    assert rec.backfill_subscriptions(conn, {}) == []

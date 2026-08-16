"""Tests de db.py: premium_subscriptions -- metadatos descriptivos de
facturación (plan, estado, período, trial), separados a propósito de
premium_guilds (que sigue siendo la única fuente de "¿tiene acceso?").
"""

import asyncio

import pytest

import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(db, "_db", None)
    asyncio.run(db.init_db())
    yield
    asyncio.run(db.close_db())


def _upsert(guild_id, **overrides):
    fields = dict(
        subscription_id="sub_1",
        customer_id="cus_1",
        purchaser_user_id="42",
        product_id="prod-monthly",
        status="active",
        current_period_start="2026-08-01T00:00:00+00:00",
        current_period_end="2026-09-01T00:00:00+00:00",
        trial_start=None,
        trial_end=None,
        cancel_at_period_end=False,
        canceled_at=None,
        event_at="2026-08-01T00:00:00+00:00",
    )
    fields.update(overrides)
    return asyncio.run(db.upsert_premium_subscription(guild_id, **fields))


def test_upsert_y_get(temp_db):
    _upsert(123)
    row = asyncio.run(db.get_premium_subscription(123))
    assert row["guild_id"] == 123
    assert row["subscription_id"] == "sub_1"
    assert row["purchaser_user_id"] == "42"
    assert row["cancel_at_period_end"] == 0


def test_get_inexistente_da_none(temp_db):
    assert asyncio.run(db.get_premium_subscription(999)) is None


def test_upsert_con_evento_mas_nuevo_pisa(temp_db):
    _upsert(123, status="active", event_at="2026-08-01T00:00:00+00:00")
    _upsert(
        123,
        status="canceled",
        cancel_at_period_end=True,
        event_at="2026-08-05T00:00:00+00:00",
    )
    row = asyncio.run(db.get_premium_subscription(123))
    assert row["status"] == "canceled"
    assert row["cancel_at_period_end"] == 1


def test_upsert_con_evento_mas_viejo_se_descarta(temp_db):
    _upsert(123, status="canceled", event_at="2026-08-05T00:00:00+00:00")
    _upsert(123, status="active", event_at="2026-08-01T00:00:00+00:00")  # más viejo
    row = asyncio.run(db.get_premium_subscription(123))
    assert row["status"] == "canceled"  # no se pisó


def test_upsert_con_event_at_none_no_pisa_una_fila_con_fecha_conocida(temp_db):
    """El caso que motivó el fix: un evento con timestamp no parseable
    (event_at=None) no puede pisar datos de un evento posterior real, o un
    reintento tardío sin timestamp legible borraría el estado más nuevo."""
    _upsert(123, status="canceled", event_at="2026-08-05T00:00:00+00:00")
    _upsert(123, status="active", event_at=None)
    row = asyncio.run(db.get_premium_subscription(123))
    assert row["status"] == "canceled"


def test_upsert_con_event_at_none_completa_una_fila_sin_fecha_previa(temp_db):
    """Si la fila existente tampoco tenía event_at confiable, sí se permite
    -- no hay nada bueno que proteger todavía."""
    _upsert(123, status="incomplete", event_at=None)
    _upsert(123, status="active", event_at=None)
    row = asyncio.run(db.get_premium_subscription(123))
    assert row["status"] == "active"


def test_list_premium_subscriptions_by_purchaser_filtra_por_dueno(temp_db):
    """El escenario central de la auditoría: A compra, B administra el mismo
    guild -- la lista de B nunca debe incluir la suscripción de A."""
    _upsert(111, purchaser_user_id="user-a")
    _upsert(222, purchaser_user_id="user-b")

    solo_a = asyncio.run(db.list_premium_subscriptions_by_purchaser("user-a"))
    solo_b = asyncio.run(db.list_premium_subscriptions_by_purchaser("user-b"))
    nadie = asyncio.run(db.list_premium_subscriptions_by_purchaser("user-c"))

    assert [r["guild_id"] for r in solo_a] == [111]
    assert [r["guild_id"] for r in solo_b] == [222]
    assert nadie == []


def test_list_premium_subscriptions_by_purchaser_no_expone_purchaser_user_id(temp_db):
    """La API pública (/api/me/billing) no debe poder reenviar el id de otro
    usuario -- el filtro ya elimina la columna del resultado."""
    _upsert(111, purchaser_user_id="user-a")
    rows = asyncio.run(db.list_premium_subscriptions_by_purchaser("user-a"))
    assert "purchaser_user_id" not in rows[0]

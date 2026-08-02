"""Ventana de interacciones por hora y por usuario (anti-farmeo de XP).

Contador en memoria, sin DB: se prueba la función pura. El reloj es
time.monotonic() dentro de chat.py, así que para viajar en el tiempo se
monkeypatchea ahí mismo en vez de dormir una hora.
"""

import cogs.chat as chat


def _reset():
    chat._mention_hits.clear()


def _clock(monkeypatch, value):
    monkeypatch.setattr(chat.time, "monotonic", lambda: value)


def test_allows_up_to_the_limit_then_blocks(monkeypatch):
    _reset()
    _clock(monkeypatch, 1000.0)
    assert [chat._consume_interaction(1, 7, 3) for _ in range(3)] == [True] * 3
    assert chat._consume_interaction(1, 7, 3) is False
    assert chat._consume_interaction(1, 7, 3) is False


def test_window_resets_after_an_hour(monkeypatch):
    _reset()
    _clock(monkeypatch, 1000.0)
    for _ in range(3):
        chat._consume_interaction(1, 7, 3)
    assert chat._consume_interaction(1, 7, 3) is False

    # 59:59 sigue bloqueado; a la hora exacta se reinicia el cupo.
    _clock(monkeypatch, 1000.0 + chat._MENTION_RATE_WINDOW - 1)
    assert chat._consume_interaction(1, 7, 3) is False
    _clock(monkeypatch, 1000.0 + chat._MENTION_RATE_WINDOW)
    assert chat._consume_interaction(1, 7, 3) is True


def test_counters_are_per_user_and_per_guild(monkeypatch):
    _reset()
    _clock(monkeypatch, 1000.0)
    for _ in range(3):
        chat._consume_interaction(1, 7, 3)
    assert chat._consume_interaction(1, 7, 3) is False
    # Otro usuario del mismo server, y el mismo usuario en otro server.
    assert chat._consume_interaction(1, 8, 3) is True
    assert chat._consume_interaction(2, 7, 3) is True


def test_zero_means_no_limit(monkeypatch):
    _reset()
    _clock(monkeypatch, 1000.0)
    assert all(chat._consume_interaction(1, 7, 0) for _ in range(50))
    # Config vieja o corrupta con negativo: tampoco debe bloquear a nadie.
    assert chat._consume_interaction(1, 9, -5) is True


def test_blocked_user_does_not_inflate_its_own_count(monkeypatch):
    """Pegar contra el tope no debe extender el bloqueo más allá de la ventana."""
    _reset()
    _clock(monkeypatch, 1000.0)
    for _ in range(2):
        chat._consume_interaction(1, 7, 2)
    for _ in range(100):
        assert chat._consume_interaction(1, 7, 2) is False
    _clock(monkeypatch, 1000.0 + chat._MENTION_RATE_WINDOW)
    assert chat._consume_interaction(1, 7, 2) is True

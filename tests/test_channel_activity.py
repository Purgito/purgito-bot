"""Tests del "termostato" de actividad reciente por canal (Fase 6):
_bump_channel_activity/_activity_multiplier en generation.py, y cómo
afectan a note_message_for_auto_generate (el timer fijo de siempre sigue
gateando CUÁNDO hay una oportunidad de hablar; la actividad reciente sube
la probabilidad de esa oportunidad, no la reemplaza).
"""

import pytest

import generation


@pytest.fixture(autouse=True)
def clean_state():
    generation._channel_activity.clear()
    generation._message_counter.clear()
    yield


def _clock(monkeypatch, value):
    monkeypatch.setattr(generation.time, "monotonic", lambda: value)


# ─── _bump_channel_activity ───────────────────────────────────────────────────


def test_mensajes_seguidos_sin_tiempo_transcurrido_se_acumulan(monkeypatch):
    _clock(monkeypatch, 1000.0)
    a = generation._bump_channel_activity(1, 10)
    b = generation._bump_channel_activity(1, 10)
    c = generation._bump_channel_activity(1, 10)
    assert (a, b, c) == (1.0, 2.0, 3.0)


def test_la_actividad_decae_con_el_tiempo(monkeypatch):
    _clock(monkeypatch, 1000.0)
    generation._bump_channel_activity(1, 10)
    generation._bump_channel_activity(1, 10)
    generation._bump_channel_activity(1, 10)  # score ~3.0

    # Una vida media completa después: el score debería haber caído a la mitad.
    _clock(monkeypatch, 1000.0 + generation._ACTIVITY_HALF_LIFE)
    score = generation._bump_channel_activity(1, 10)
    # +1.0 nuevo sobre el decay de los 3.0 previos.
    assert score == pytest.approx(3.0 * 0.5 + 1.0, rel=1e-6)


def test_mucho_tiempo_sin_mensajes_la_actividad_vuelve_a_casi_cero(monkeypatch):
    _clock(monkeypatch, 1000.0)
    generation._bump_channel_activity(1, 10)

    _clock(monkeypatch, 1000.0 + generation._ACTIVITY_HALF_LIFE * 20)
    score = generation._bump_channel_activity(1, 10)
    # Los 20 vidas medias previas decayeron a ~0; queda solo el +1.0 de ahora.
    assert score == pytest.approx(1.0, abs=1e-4)


def test_canales_y_guilds_no_se_mezclan(monkeypatch):
    _clock(monkeypatch, 1000.0)
    generation._bump_channel_activity(1, 10)
    generation._bump_channel_activity(1, 10)
    generation._bump_channel_activity(1, 20)
    generation._bump_channel_activity(2, 10)

    assert generation._channel_activity[(1, 10)][0] == 2.0
    assert generation._channel_activity[(1, 20)][0] == 1.0
    assert generation._channel_activity[(2, 10)][0] == 1.0


# ─── _activity_multiplier ─────────────────────────────────────────────────────


def test_sin_actividad_el_multiplicador_es_neutro():
    assert generation._activity_multiplier(0.0) == 1.0


def test_el_multiplicador_sube_con_la_actividad():
    assert generation._activity_multiplier(generation._ACTIVITY_PER_BOOST) == 2.0


def test_el_multiplicador_tiene_techo():
    assert generation._activity_multiplier(10_000.0) == generation._ACTIVITY_BOOST_CAP


# ─── note_message_for_auto_generate: la actividad sube la probabilidad ──────


def test_canal_activo_dispara_donde_uno_tranquilo_no_dispara(monkeypatch):
    """Mismo every/probability, mismo roll de random(); la única diferencia
    es cuánta actividad reciente tiene el canal."""
    _clock(monkeypatch, 1000.0)

    # random() = 0.55 -- falla contra probability=0.5 sola, pero pasa si el
    # boost de actividad la sube lo suficiente.
    monkeypatch.setattr(generation.random, "random", lambda: 0.55)

    # Canal tranquilo: cae directo en el every-ésimo mensaje sin actividad previa.
    quiet_result = generation.note_message_for_auto_generate(
        1, 10, every=1, probability=0.5
    )
    assert quiet_result is False

    # Canal caliente: mucha actividad acumulada antes del mensaje que dispara.
    for _ in range(20):
        generation._bump_channel_activity(1, 20)
    hot_result = generation.note_message_for_auto_generate(
        1, 20, every=1, probability=0.5
    )
    assert hot_result is True


def test_la_probabilidad_boosteada_nunca_supera_el_cap_de_095(monkeypatch):
    _clock(monkeypatch, 1000.0)
    for _ in range(1000):
        generation._bump_channel_activity(1, 10)  # actividad extrema

    monkeypatch.setattr(generation.random, "random", lambda: 0.951)

    result = generation.note_message_for_auto_generate(1, 10, every=1, probability=0.9)
    # random()=0.951 > el tope de 0.95: para probability < 1.0 el boost
    # nunca supera 0.95.
    assert result is False


def test_probabilidad_1_0_siempre_dispara(monkeypatch):
    """probability=1.0 configurado explícitamente dispara siempre al cumplirse every."""
    _clock(monkeypatch, 1000.0)
    monkeypatch.setattr(generation.random, "random", lambda: 0.999)
    result = generation.note_message_for_auto_generate(1, 10, every=1, probability=1.0)
    assert result is True


def test_sin_boost_se_comporta_igual_que_antes(monkeypatch):
    """Sin actividad previa acumulada (primer mensaje del canal), el
    multiplicador es 1.0 y el resultado es exactamente probability."""
    _clock(monkeypatch, 1000.0)
    monkeypatch.setattr(generation.random, "random", lambda: 0.59)

    assert (
        generation.note_message_for_auto_generate(1, 10, every=1, probability=0.6)
        is True
    )
    monkeypatch.setattr(generation.random, "random", lambda: 0.61)
    assert (
        generation.note_message_for_auto_generate(1, 20, every=1, probability=0.6)
        is False
    )


# ─── reset_guild_caches limpia también la actividad ─────────────────────────


def test_reset_guild_caches_limpia_la_actividad(monkeypatch):
    _clock(monkeypatch, 1000.0)
    generation._bump_channel_activity(1, 10)
    generation._bump_channel_activity(2, 10)

    generation.reset_guild_caches(1)

    assert (1, 10) not in generation._channel_activity
    assert (2, 10) in generation._channel_activity

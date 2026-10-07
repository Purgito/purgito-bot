"""restart_loop_after_failure (utils.py): cuerpo común de los @loop.error.

Antes cada handler hacía `log.exception(...)` + `loop.restart()` a ciegas: un
error SISTEMÁTICO reejecutaba el cuerpo del loop en el acto y en bucle (un
traceback por vuelta) y nadie se enteraba de que la función llevaba horas sin
andar. Ahora los fallos se cuentan en una ventana, el reinicio espera cada vez
más y, pasado un umbral, se loguea a nivel CRITICAL."""

import asyncio
import logging
from types import SimpleNamespace

import pytest

import utils


class FakeLoop:
    """Suficiente de discord.ext.tasks.Loop para el helper: un __dict__ donde
    guardar estado y un restart() que registra la llamada."""

    def __init__(self):
        self.restarts = 0

    def restart(self):
        self.restarts += 1


@pytest.fixture
def entorno(monkeypatch):
    """Reloj controlable + sleep registrado, sin esperar de verdad."""
    estado = SimpleNamespace(now=1000.0, sleeps=[])

    async def fake_sleep(segundos):
        estado.sleeps.append(segundos)

    monkeypatch.setattr(utils.time, "monotonic", lambda: estado.now)
    monkeypatch.setattr(utils.asyncio, "sleep", fake_sleep)
    return estado


def _criticos(caplog):
    return [r for r in caplog.records if r.levelno == logging.CRITICAL]


def _fallar(loop, nombre="check_x", bot=None):
    asyncio.run(
        utils.restart_loop_after_failure(
            bot or SimpleNamespace(), loop, nombre, RuntimeError("boom")
        )
    )


def test_el_primer_fallo_reinicia_de_inmediato_y_sin_aviso(entorno, caplog):
    loop = FakeLoop()
    with caplog.at_level(logging.CRITICAL, logger="utils"):
        _fallar(loop)
    assert loop.restarts == 1
    assert entorno.sleeps == []
    assert _criticos(caplog) == []


def test_los_fallos_repetidos_esperan_cada_vez_mas(entorno):
    loop = FakeLoop()
    for _ in range(5):
        _fallar(loop)
        entorno.now += 1
    assert entorno.sleeps == [10, 20, 40, 80]  # el 1.º no espera
    assert loop.restarts == 5  # sigue reiniciando: la función no se apaga


def test_la_espera_tiene_techo(entorno):
    loop = FakeLoop()
    for _ in range(14):
        _fallar(loop)
        entorno.now += 1
    assert max(entorno.sleeps) == utils._LOOP_RESTART_DELAY_MAX


def test_loguea_critical_al_tercer_fallo_y_no_repite_dentro_del_cooldown(
    entorno, caplog
):
    loop = FakeLoop()
    with caplog.at_level(logging.CRITICAL, logger="utils"):
        for _ in range(6):
            _fallar(loop, nombre="check_rss")
            entorno.now += 1
    criticos = _criticos(caplog)
    assert len(criticos) == 1
    assert "check_rss" in criticos[0].getMessage()
    assert "3 veces" in criticos[0].getMessage()


def test_vuelve_a_loguear_pasado_el_cooldown(entorno, caplog):
    loop = FakeLoop()
    with caplog.at_level(logging.CRITICAL, logger="utils"):
        for _ in range(3):
            _fallar(loop)
            entorno.now += 1
        assert len(_criticos(caplog)) == 1
        entorno.now += utils._LOOP_ALERT_COOLDOWN + 1
        for _ in range(3):  # tres fallos más dentro de una ventana nueva
            _fallar(loop)
            entorno.now += 1
    assert len(_criticos(caplog)) == 2


def test_los_fallos_viejos_salen_de_la_ventana(entorno, caplog):
    loop = FakeLoop()
    with caplog.at_level(logging.CRITICAL, logger="utils"):
        for _ in range(2):
            _fallar(loop)
            entorno.now += 1
        entorno.now += utils._LOOP_FAILURE_WINDOW + 10  # ya no cuentan
        _fallar(loop)
    assert _criticos(caplog) == []  # 1 fallo en la ventana, no 3
    assert entorno.sleeps == [10]  # solo el segundo fallo de la tanda vieja esperó


def test_cada_loop_lleva_su_propia_cuenta(entorno, caplog):
    a, b = FakeLoop(), FakeLoop()
    with caplog.at_level(logging.CRITICAL, logger="utils"):
        for _ in range(3):
            _fallar(a)
            entorno.now += 1
        _fallar(b)
    assert len(_criticos(caplog)) == 1  # solo a llegó al umbral
    assert b.restarts == 1 and entorno.sleeps.count(0) == 0


def test_loguea_la_causa_real_con_traceback(entorno, caplog):
    loop = FakeLoop()
    original = ValueError("algo específico")
    with caplog.at_level(logging.ERROR, logger="utils"):
        asyncio.run(
            utils.restart_loop_after_failure(
                SimpleNamespace(), loop, "check_y", original
            )
        )
    rec = next(
        r for r in caplog.records if "se cayó, reiniciando el loop" in r.getMessage()
    )
    assert rec.exc_info[1] is original
    assert "check_y" in rec.getMessage()


def test_loguea_critical_al_llegar_al_umbral(entorno, caplog):
    loop = FakeLoop()
    with caplog.at_level(logging.CRITICAL, logger="utils"):
        for _ in range(3):
            _fallar(loop)
            entorno.now += 1
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)

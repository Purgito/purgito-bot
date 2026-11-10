"""Lógica de silencio/avisos del vigilante de salud (sin red, sin systemd)."""

import importlib.util
import json
import os
import time

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "purgito_salud",
    os.path.join(os.path.dirname(__file__), "..", "deploy", "purgito_salud.py"),
)


@pytest.fixture()
def salud(tmp_path, monkeypatch):
    monkeypatch.setenv("SALUD_STATE_DIR", str(tmp_path))
    monkeypatch.syspath_prepend(os.path.join(os.path.dirname(__file__), "..", "deploy"))
    mod = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(mod)
    sent = []
    monkeypatch.setattr(mod, "send", lambda probs, **kw: sent.append((dict(probs), kw)) or True)
    mod.sent = sent
    mod.tmp = tmp_path
    return mod


def run(mod, monkeypatch, problems, uptime=7200):
    monkeypatch.setattr(mod, "check", lambda state: dict(problems))
    monkeypatch.setattr(mod, "uptime_s", lambda: uptime)
    mod.main([])
    mod.main([])  # confirmación: dos comprobaciones seguidas


def test_boveda_cerrada_avisa_aunque_haya_mantenimiento(salud, monkeypatch):
    (salud.tmp / "mantenimiento-hasta").write_text(str(int(time.time()) + 3 * 3600))
    run(salud, monkeypatch, {"boveda": "cerrada"})
    assert salud.sent and "boveda" in salud.sent[0][0]


def test_boveda_cerrada_en_gracia_de_arranque_no_avisa(salud, monkeypatch):
    run(salud, monkeypatch, {"boveda": "cerrada"}, uptime=120)
    assert not salud.sent


def test_problema_normal_se_silencia_con_mantenimiento(salud, monkeypatch):
    (salud.tmp / "mantenimiento-hasta").write_text(str(int(time.time()) + 600))
    run(salud, monkeypatch, {"unidad:bot-purg.service": "parado"})
    assert not salud.sent


def test_mantenimiento_largo_se_recorta_a_una_hora(salud, monkeypatch):
    f = salud.tmp / "mantenimiento-hasta"
    f.write_text(str(int(time.time()) + 20 * 3600))
    old = time.time() - 2 * 3600  # creado hace 2 h
    os.utime(f, (old, old))
    run(salud, monkeypatch, {"unidad:bot-purg.service": "parado"})
    assert salud.sent


def test_recordatorio_critico_cada_30_min(salud, monkeypatch):
    run(salud, monkeypatch, {"boveda": "cerrada"})
    assert len(salud.sent) == 1
    st = json.loads((salud.tmp / "estado.json").read_text())
    st["notified_at"] = time.time() - 1900
    (salud.tmp / "estado.json").write_text(json.dumps(st))
    run(salud, monkeypatch, {"boveda": "cerrada"})
    assert len(salud.sent) == 2 and salud.sent[1][1].get("reminder") is True

"""Precedencia de la configuración: limits.env y urls.env (versionados) mandan
sobre un valor duplicado por accidente en .env; lo que solo está en .env
(secretos, config de instancia) se conserva."""

import logging
import os

import pytest

import config


@pytest.fixture
def raiz(tmp_path):
    """Carpeta con los tres archivos; restaura os.environ al terminar."""
    antes = dict(os.environ)
    (tmp_path / ".env").write_text(
        "T_LIMITE=111\nT_URL=https://viejo.example\nT_SECRETO=solo-en-env\n"
    )
    (tmp_path / "limits.env").write_text("T_LIMITE=222\nT_LIMITE_SOLO=333\n")
    (tmp_path / "urls.env").write_text("T_URL=https://nuevo.example\n")
    yield tmp_path
    os.environ.clear()
    os.environ.update(antes)


def test_limits_env_gana_sobre_env(raiz):
    config.load_env_files(str(raiz))
    assert os.environ["T_LIMITE"] == "222"


def test_urls_env_gana_sobre_env(raiz):
    config.load_env_files(str(raiz))
    assert os.environ["T_URL"] == "https://nuevo.example"


def test_versionados_ganan_sobre_el_entorno_del_proceso(raiz, monkeypatch):
    monkeypatch.setenv("T_LIMITE_SOLO", "999")
    config.load_env_files(str(raiz))
    assert os.environ["T_LIMITE_SOLO"] == "333"


def test_variables_solo_de_env_se_conservan(raiz):
    config.load_env_files(str(raiz))
    assert os.environ["T_SECRETO"] == "solo-en-env"


def test_duplicados_se_reportan_sin_valores(raiz, caplog):
    assert config.duplicated_env_names(str(raiz)) == {
        "T_LIMITE": ["limits.env"],
        "T_URL": ["urls.env"],
    }
    with caplog.at_level(logging.WARNING, logger="config"):
        config.load_env_files(str(raiz))
    texto = caplog.text
    assert "T_LIMITE" in texto and "T_URL" in texto
    assert "111" not in texto and "viejo.example" not in texto


def test_repo_sin_duplicados_entre_env_y_versionados():
    """limits.env y urls.env no pueden compartir nombres entre sí."""
    from dotenv import dotenv_values

    limits = set(dotenv_values(config._ROOT_DIR + "/limits.env"))
    urls = set(dotenv_values(config._ROOT_DIR + "/urls.env"))
    assert not limits & urls

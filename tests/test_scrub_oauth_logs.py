"""scripts/scrub_oauth_logs.py: sanea valores sensibles de logs históricos sin perder la evidencia."""

import gzip
import importlib.util
import json
import os
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "scrub_oauth_logs", ROOT / "scripts" / "scrub_oauth_logs.py"
)
scrub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scrub)

LINE = '127.0.0.1 - - [07/Nov/2026:00:17:52 +0000] "GET /auth/callback?code=SECRETO123&state=ESTADO456 HTTP/1.1" 302 0 "-" "Mozilla/5.0"\n'
OTRA = '127.0.0.1 - - [07/Nov/2026:00:18:00 +0000] "GET /health HTTP/1.1" 200 2 "-" "curl/8"\n'


def _viejo(path):
    t = time.time() - 3600
    os.utime(path, (t, t))


def test_ensayo_no_cambia_nada_y_no_imprime_valores(tmp_path, capsys):
    f = tmp_path / "access.log.1"
    f.write_text(OTRA + LINE, encoding="utf-8")
    _viejo(f)
    antes = f.read_bytes()
    assert scrub.main([str(f)]) == 0
    salida = capsys.readouterr().out
    assert f.read_bytes() == antes
    assert "SECRETO123" not in salida and "ESTADO456" not in salida
    assert "code×1" in salida and "state×1" in salida


def test_aplicar_cambia_solo_los_valores_y_conserva_el_resto(tmp_path):
    f = tmp_path / "access.log.1"
    f.write_text(OTRA + LINE, encoding="utf-8")
    os.chmod(f, 0o640)
    _viejo(f)
    mtime = f.stat().st_mtime_ns
    assert scrub.main(["--apply", str(f)]) == 0
    texto = f.read_text(encoding="utf-8")
    assert "SECRETO123" not in texto and "ESTADO456" not in texto
    assert "GET /auth/callback?code=[redactado]&state=[redactado] HTTP/1.1" in texto
    assert (
        texto.count("\n") == 2
        and OTRA in texto
        and '" 302 0 "-" "Mozilla/5.0"' in texto
    )
    assert oct(f.stat().st_mode & 0o777) == "0o640" and f.stat().st_mtime_ns == mtime
    assert not [
        n for n in os.listdir(tmp_path) if n.startswith(".scrub-") or n.endswith(".bak")
    ]


def test_gz_y_texto_de_bot_log(tmp_path):
    g = tmp_path / "access.log.2.gz"
    with gzip.open(g, "wt", encoding="utf-8") as fh:
        fh.write(LINE)
    b = tmp_path / "bot.log.2"
    b.write_text(
        '2026-10-31 04:06:09 INFO aiohttp.access: 127.0.0.1 "GET /cb?code=ABC&x=1 HTTP/1.0" 302\n',
        encoding="utf-8",
    )
    _viejo(g)
    _viejo(b)
    assert scrub.main(["--apply", str(g), str(b)]) == 0
    assert "SECRETO123" not in gzip.open(g, "rt", encoding="utf-8").read()
    assert "ABC" not in b.read_text(encoding="utf-8") and "x=1" in b.read_text(
        encoding="utf-8"
    )


def test_no_toca_archivos_activos_ni_recientes(tmp_path, capsys):
    activo = tmp_path / "access.log"
    activo.write_text(LINE, encoding="utf-8")
    _viejo(activo)
    reciente = tmp_path / "access.log.1"
    reciente.write_text(LINE, encoding="utf-8")  # mtime = ahora
    assert scrub.main(["--apply", str(activo), str(reciente)]) == 0
    assert "SECRETO123" in activo.read_text(encoding="utf-8")
    assert "SECRETO123" in reciente.read_text(encoding="utf-8")
    assert "archivo activo" in capsys.readouterr().out


def test_informe_sin_valores_y_con_las_lineas_afectadas(tmp_path):
    f = tmp_path / "access.log.1"
    f.write_text(OTRA + LINE, encoding="utf-8")
    _viejo(f)
    rep = tmp_path / "rep.json"
    assert scrub.main(["--apply", "--report", str(rep), str(f)]) == 0
    crudo = rep.read_text(encoding="utf-8")
    assert "SECRETO123" not in crudo and "ESTADO456" not in crudo
    data = json.loads(crudo)
    assert data["files"][0]["lines"] == [2] and data["files"][0]["params"] == {
        "code": 1,
        "state": 1,
    }
    assert oct(rep.stat().st_mode & 0o777) == "0o600"

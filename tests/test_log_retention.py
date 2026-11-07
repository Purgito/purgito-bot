"""Retención por tiempo de los logs (identificador derivado de la IP) y access log sin query strings."""

import logging
import os
import time
from datetime import datetime, timedelta, timezone

from observability import logging_setup as ls

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def _jsonl(ts: str, extra: str = "") -> str:
    return (
        '{"event_type": "auth.login_failed", "source_id": "ab12", "timestamp": "%s"%s}\n'
        % (ts, extra)
    )


def test_trim_quita_lo_anterior_al_plazo_y_conserva_lo_reciente(tmp_path):
    p = tmp_path / "security.jsonl"
    p.write_text(
        _jsonl("2026-10-02T19:31:18.235Z")
        + _jsonl("2026-10-07T00:00:00.000Z")  # >30 días
        + _jsonl("2026-10-20T10:00:00.000Z")
        + _jsonl("2026-11-06T22:30:00.000Z"),
        encoding="utf-8",
    )
    os.chmod(p, 0o600)
    assert ls.trim_old_lines(str(p), 30, NOW) == 2
    left = p.read_text(encoding="utf-8")
    assert "2026-10-02" not in left and "2026-10-07" not in left
    assert "2026-10-20" in left and "2026-11-06" in left
    assert oct(os.stat(p).st_mode & 0o777) == "0o600"


def test_trim_acepta_el_formato_de_texto_y_conserva_las_lineas_sin_fecha(tmp_path):
    p = tmp_path / "bot.log"
    p.write_text(
        '2026-09-30 08:18:42,212 INFO x: viejo\n  File "a.py", line 1\n'
        "2026-11-07 08:18:42,212 INFO x: nuevo\n",
        encoding="utf-8",
    )
    assert ls.trim_old_lines(str(p), 30, NOW) == 1
    assert "viejo" not in p.read_text(encoding="utf-8") and "nuevo" in p.read_text(
        encoding="utf-8"
    )


def test_trim_legacy_borra_copias_numeradas_viejas(tmp_path):
    base = tmp_path / "events.jsonl"
    base.write_text(_jsonl("2026-11-07T10:00:00.000Z"), encoding="utf-8")
    old, fresh = tmp_path / "events.jsonl.2", tmp_path / "events.jsonl.1"
    old.write_text(_jsonl("2026-09-01T00:00:00.000Z"), encoding="utf-8")
    fresh.write_text(_jsonl("2026-11-06T00:00:00.000Z"), encoding="utf-8")
    viejo = time.time() - 40 * 86400
    os.utime(old, (viejo, viejo))
    ls.trim_legacy_logs(str(base), 30)
    assert not old.exists() and fresh.exists() and base.exists()


def test_el_handler_borra_segmentos_viejos_y_no_los_recientes(tmp_path):
    path = tmp_path / "security.jsonl"
    hoy = datetime.now(timezone.utc)
    viejo = (
        tmp_path
        / f"security.jsonl.{(hoy - timedelta(days=45)).strftime(ls._SEGMENT_SUFFIX)}"
    )
    reciente = (
        tmp_path
        / f"security.jsonl.{(hoy - timedelta(days=3)).strftime(ls._SEGMENT_SUFFIX)}"
    )
    ajeno = tmp_path / "security.jsonl.bak"
    for f in (viejo, reciente, ajeno):
        f.write_text("x\n", encoding="utf-8")
    h = ls.RetainedFileHandler(str(path), 30)
    try:
        assert [os.path.basename(f) for f in h.getFilesToDelete()] == [viejo.name]
        h.doRollover()
    finally:
        h.close()
    assert not viejo.exists() and reciente.exists() and ajeno.exists()


def test_el_handler_rota_por_tamano_sin_pisar_segmentos(tmp_path):
    path = tmp_path / "events.jsonl"
    h = ls.RetainedFileHandler(str(path), 30, max_bytes=300)
    log = logging.getLogger("test_retained_size")
    log.setLevel(logging.INFO)
    log.addHandler(h)
    try:
        for i in range(30):
            log.info("x" * 80 + str(i))
    finally:
        log.removeHandler(h)
        h.close()
    segmentos = [n for n in os.listdir(tmp_path) if n.startswith("events.jsonl.")]
    assert len(segmentos) >= 3 and len(set(segmentos)) == len(segmentos)
    total = sum(sum(1 for _ in open(tmp_path / n)) for n in os.listdir(tmp_path))
    assert total == 30  # ninguna línea se perdió al rotar


def test_el_access_log_pierde_la_query_string_y_la_del_referer():
    f = ls.QueryStringFilter()
    msg = (
        '127.0.0.1 [07/Nov/2026:12:00:00 +0000] "GET /auth/callback?code=SECRETO&state=abc HTTP/1.0" '
        '302 0 "https://purgito.app/es/perfil?token=otro" "Mozilla/5.0"'
    )
    rec = logging.LogRecord("aiohttp.access", logging.INFO, "", 0, msg, None, None)
    assert f.filter(rec)
    assert (
        "SECRETO" not in rec.msg and "token=" not in rec.msg and "state=" not in rec.msg
    )
    assert "GET /auth/callback?- HTTP/1.0" in rec.msg
    otro = logging.LogRecord("bot", logging.INFO, "", 0, "pregunta? sí", None, None)
    f.filter(otro)
    assert otro.msg == "pregunta? sí"  # solo toca aiohttp.access


def test_trim_mira_el_timestamp_aunque_la_linea_sea_larga_y_recorta_segmentos_por_fecha(
    tmp_path,
):
    def ts(days_ago):
        d = datetime.now(timezone.utc) - timedelta(days=days_ago)
        return d.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    largo = (
        '{"data": {"x": "' + "a" * 900 + '"}, "event_type": "x.y", "timestamp": "%s"}\n'
    )
    base = tmp_path / "events.jsonl"
    seg = tmp_path / "events.jsonl.2026-11-06_000000"
    base.write_text(largo % ts(40) + largo % ts(2), encoding="utf-8")
    seg.write_text(largo % ts(45) + largo % ts(3), encoding="utf-8")
    ls.trim_legacy_logs(str(base), 30)
    for f in (base, seg):
        left = f.read_text(encoding="utf-8")
        assert (
            left.count("\n") == 1
            and ts(40)[:10] not in left
            and ts(45)[:10] not in left
        ), f

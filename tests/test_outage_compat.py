"""Compatibilidad entre dumps, registro de eliminaciones (lápidas de 15 días) y las reglas de R2 cuando el
servidor queda apagado o con la bóveda cerrada días o semanas.

Modelo: hasta el instante D el servicio funciona (dump diario 03:17, registro cada 30 min, con las podas
reales); desde D no corre nada y solo actúa el lifecycle de Cloudflare, que borra «típicamente dentro de las
24 h» posteriores a la expiración (peor caso modelado: los dumps con +24 h de retraso y el registro sin
retraso). Reglas modeladas: dumps 13 d, registro 14 d (docs/R2_REGLAS.md)."""

from datetime import datetime, timedelta, timezone

from test_retention_lock_compat import _name, r2_backup

DUMP_LIFECYCLE = timedelta(days=13)
LEDGER_LIFECYCLE = timedelta(days=14)
TOMBSTONE = timedelta(days=15)
JITTER = timedelta(hours=24)
START = datetime(2026, 3, 1, 3, 17, 9, tzinfo=timezone.utc)


def _ledger_key(t):
    return "ledger/privacy-ledger-" + t.strftime("%Y%m%dT%H%M%S") + "Z.jsonl.age"


def _estado_al_apagarse(D):
    """Objetos vivos justo antes de que el servicio deje de correr en D (días desde START)."""
    apagon = START + timedelta(days=D, hours=5)
    dumps = {}
    for d in range(D + 1):
        t = START + timedelta(days=d)
        dumps[_name(t)] = t
        _v, _k, victims = r2_backup.prune_plan_gfs(
            [(k, 1, None) for k in dumps],
            t,
            min_age_days=r2_backup.DEFAULT_MIN_AGE_DAYS,
        )
        for k in victims:
            del dumps[k]
    ledger = {}
    t = max(START, apagon - timedelta(days=20))
    while t <= apagon:
        ledger[_ledger_key(t)] = t
        t += timedelta(minutes=30)
    _k, _kept, victims = r2_backup.prune_plan_ledger(
        [(k, 1, None) for k in ledger], apagon
    )
    for k in victims:
        del ledger[k]
    return apagon, dumps, ledger


def test_tras_un_apagon_largo_nunca_queda_un_dump_sin_su_registro_mas_de_un_dia():
    for D in range(20, 60, 3):
        apagon, dumps, ledger = _estado_al_apagarse(D)
        ultimo_registro = max(ledger.values())
        sin_registro = []  # instantes con algún dump vivo pero ningún registro
        T = apagon
        while T <= apagon + timedelta(days=40):
            dumps_vivos = [c for c in dumps.values() if T - c < DUMP_LIFECYCLE + JITTER]
            ledger_vivo = [c for c in ledger.values() if T - c < LEDGER_LIFECYCLE]
            # 1. el lifecycle acota la edad de cualquier dump restaurable
            for c in dumps_vivos:
                assert T - c < timedelta(days=14, minutes=1), (D, T, c)
            if dumps_vivos:
                if ledger_vivo:
                    # 2. si hay registro, cubre toda eliminación posterior al dump más viejo restaurable
                    assert ultimo_registro - min(dumps_vivos) <= TOMBSTONE, (D, T)
                else:
                    sin_registro.append(T)
            T += timedelta(hours=1)
        # 3. la única brecha posible (registro ya expirado con un dump todavía vivo) es el desfase del
        #    proveedor; en ella `reapply_deletions.py` exige --sin-registro: falla de forma explícita.
        if sin_registro:
            assert sin_registro[-1] - sin_registro[0] <= JITTER, (
                D,
                sin_registro[0],
                sin_registro[-1],
            )

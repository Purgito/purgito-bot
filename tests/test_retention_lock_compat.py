"""La poda de R2 frente a las reglas de Cloudflare (Bucket Lock y Lifecycle).

Reglas configuradas en purgito-backups:
  - Bucket Lock 6 días sobre gen2/purgito-  (nada se puede borrar antes)
  - Lifecycle   14 días sobre gen2/purgito- (R2 lo borra solo a los 14 días)
  - Lifecycle   15 días sobre gen2/ledger/
  - Bucket Lock 14 días sobre lo histórico de la raíz (purgito-, luks-header, privacy-prefs)

Se simulan 400 días de backups diarios a las 03:17 más backups manuales a horas raras, y
instantáneas del registro cada hora, aplicando exactamente el plan de poda del código.
"""

import importlib.util
import pathlib
import random
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "r2_backup", ROOT / "scripts" / "r2_backup.py"
)
r2_backup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(r2_backup)

LOCK_DAYS = 6
LIFECYCLE_DAYS = 13
LEDGER_LIFECYCLE_DAYS = 15


def _name(dt):
    return dt.strftime("purgito-%Y%m%d-%H%M%S.dump.age")


def _simular(dias, min_age_days, semilla=7):
    """Backups diarios a las 03:17 + manuales a horas raras (cada uno seguido de su poda), en
    orden de tiempo, con el lifecycle de 14 días de R2. Devuelve las métricas relevantes."""
    rnd = random.Random(semilla)
    inicio = datetime(2026, 1, 1, 3, 17, 1, tzinfo=timezone.utc)
    eventos = []
    for d in range(dias):
        dia = inicio + timedelta(days=d)
        eventos.append(dia)
        if rnd.random() < 0.25:
            eventos.append(
                dia.replace(
                    hour=rnd.randrange(24),
                    minute=rnd.randrange(60),
                    second=rnd.randrange(60),
                )
            )
        if rnd.random() < 0.05:
            eventos.append(dia.replace(hour=23, minute=59, second=59))
    eventos.sort()

    objetos: dict[str, datetime] = {}
    m = {
        "intentos_bloqueados": [],
        "peor_victima": timedelta(days=999),
        "max_edad": timedelta(0),
        "max_objetos": 0,
    }
    for t in eventos:
        objetos[_name(t)] = t
        ahora = t + timedelta(seconds=50)
        for k in [
            k for k, c in objetos.items() if ahora - c >= timedelta(days=LIFECYCLE_DAYS)
        ]:
            del objetos[k]  # lifecycle de R2
        listing = [(k, 1, None) for k in objetos]
        _v, kept, victims = r2_backup.prune_plan_gfs(
            listing, ahora, min_age_days=min_age_days
        )
        for k in victims:
            edad = ahora - objetos[k]
            m["peor_victima"] = min(m["peor_victima"], edad)
            if edad < timedelta(days=LOCK_DAYS):
                m["intentos_bloqueados"].append((k, edad))
            del objetos[k]
        for k in kept:
            m["max_edad"] = max(m["max_edad"], ahora - objetos[k])
        m["max_objetos"] = max(m["max_objetos"], len(objetos))
    return m


def test_sin_proteccion_un_backup_manual_el_mismo_dia_chocaria_con_el_bucket_lock():
    """Documenta el fallo que corrige min_age_days: sin él la poda intenta borrar objetos
    bloqueados (HTTP 409 en cada pasada y alertas falsas)."""
    assert _simular(120, min_age_days=0)["intentos_bloqueados"]


def test_la_poda_nunca_intenta_borrar_algo_bloqueado_ni_conserva_nada_de_14_dias():
    m = _simular(400, min_age_days=r2_backup.DEFAULT_MIN_AGE_DAYS)
    assert m["intentos_bloqueados"] == [], m["intentos_bloqueados"][:3]
    assert m["peor_victima"] >= timedelta(days=LOCK_DAYS)
    assert m["max_edad"] < timedelta(days=14)  # política de privacidad
    assert m["max_objetos"] <= 7 + 2 + 8  # diarios + domingos + extras aún protegidos


def test_el_minimo_por_defecto_coincide_con_el_bucket_lock_documentado():
    assert r2_backup.DEFAULT_MIN_AGE_DAYS == LOCK_DAYS
    assert (
        LOCK_DAYS < 7
    )  # los diarios se podan a los 7 días: un bloqueo mayor rompería la poda


def test_el_lifecycle_de_14_dias_no_se_lleva_nada_que_la_poda_quiera_conservar():
    """Todo lo que la poda conserva tiene menos de 14 días: el lifecycle nunca corta antes."""
    ahora = datetime(2026, 11, 12, 3, 17, 50, tzinfo=timezone.utc)  # jueves
    listing = [
        (_name(ahora - timedelta(days=d, seconds=49)), 1, None) for d in range(40)
    ]
    _v, kept, _victims = r2_backup.prune_plan_gfs(listing, ahora)
    for k in kept:
        assert ahora - r2_backup.backup_time(k) < timedelta(days=LIFECYCLE_DAYS)


def test_registro_cada_5_min_poda_y_lifecycle_de_15_dias_son_compatibles():
    """60 días a ritmo real (una instantánea cada 5 min): el adelgazamiento deja pocos objetos,
    siempre quedan las 3 últimas, nada supera el tope de 15 días y la regla de lifecycle (que
    borraría a los 15 días) nunca se lleva algo que la poda quisiera conservar."""
    inicio = datetime(2026, 1, 1, 0, 2, 0, tzinfo=timezone.utc)
    objetos: dict[str, datetime] = {}
    maximo = 0
    for i in range(24 * 12 * 60):
        t = inicio + timedelta(minutes=5 * i)
        objetos[
            "ledger/privacy-ledger-" + t.strftime("%Y%m%dT%H%M%S") + "Z.jsonl.age"
        ] = t
        for k in [
            k
            for k, c in objetos.items()
            if t - c >= timedelta(days=LEDGER_LIFECYCLE_DAYS)
        ]:
            del objetos[k]
        _keys, kept, victims = r2_backup.prune_plan_ledger(
            [(k, 1, None) for k in objetos], t
        )
        for k in kept:  # lo conservado nunca llega al tope que borraría el lifecycle
            assert t - objetos[k] < timedelta(days=LEDGER_LIFECYCLE_DAYS)
        for k in victims:
            del objetos[k]
        assert len(objetos) >= min(3, i + 1)  # siempre quedan las últimas
        maximo = max(maximo, len(objetos))
    assert maximo <= 150  # ~72 (6 h) + 42 (por hora) + 15 (por día) + margen, no ~4 300


def test_la_poda_solo_ve_gen2_aunque_el_historico_cumpla_los_14_dias(monkeypatch):
    """El histórico lo borra el titular (o el lifecycle opcional), nunca la poda."""
    import r2
    from fake_s3 import FakeS3

    fake = FakeS3("purgito-backups")
    for k in (
        "purgito-20261105-000130.dump.age",
        "purgito-20261105-014330.dump.age",
        "luks-header-20261105.img.age",
        "privacy-prefs.csv.age",
    ):
        fake.seed("purgito-backups", k, b"historico")
    monkeypatch.setattr(r2, "get_backup_client", lambda: fake)
    monkeypatch.setenv("R2_BACKUP_BUCKET", "purgito-backups")
    ahora = datetime.now(timezone.utc)
    for d in range(30):
        fake.seed("purgito-backups", "gen2/" + _name(ahora - timedelta(days=d)), b"n")
    assert r2_backup.main(["prune-gfs", "--apply"]) == 0
    assert r2_backup.main(["prune-ledger", "--apply"]) == 0
    assert {k for k in fake.keys("purgito-backups") if not k.startswith("gen2/")} == {
        "purgito-20261105-000130.dump.age",
        "purgito-20261105-014330.dump.age",
        "luks-header-20261105.img.age",
        "privacy-prefs.csv.age",
    }


def test_ninguna_copia_llega_a_vivir_14_dias_con_una_poda_diaria():
    """Simula 90 días con poda diaria a las 03:17 y un dump cada día: la edad máxima que alcanza
    cualquier copia (justo antes de borrarse) es < 14 días, aunque sea de un domingo."""
    inicio = datetime(2026, 1, 1, 3, 17, 9, tzinfo=timezone.utc)
    vivos: dict[str, datetime] = {}
    maxima = timedelta(0)
    for d in range(90):
        ahora = inicio + timedelta(days=d)
        vivos[_name(ahora)] = ahora
        _v, _kept, victims = r2_backup.prune_plan_gfs(
            [(k, 1, None) for k in vivos],
            ahora,
            min_age_days=r2_backup.DEFAULT_MIN_AGE_DAYS,
        )
        for k in victims:
            maxima = max(maxima, ahora - vivos[k])
            del vivos[k]
        for c in vivos.values():
            maxima = max(maxima, ahora - c)
    assert maxima + timedelta(days=1) < timedelta(days=14, hours=1), (
        maxima
    )  # y mañana también

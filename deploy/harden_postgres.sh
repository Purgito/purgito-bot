#!/bin/bash
# Endurece PostgreSQL (idempotente; necesita sudo). Es lo que se aplicó a mano en
# producción el 2026-10-02; sirve para reproducirlo en un servidor nuevo.
#
#   sudo deploy/harden_postgres.sh [rol_de_la_app]     # default: purgito_app
#
#  - idle_in_transaction_session_timeout=5min para el rol de la app (nunca
#    debería haber una transacción abierta sin actividad; corta las que queden
#    colgadas por un bug antes de que retengan una conexión del pool).
#  - log_min_duration_statement=500ms (queries lentas) con log_parameter_max_length=0:
#    el log trae la query pero NUNCA los valores de los parámetros (mensajes de
#    usuarios, tokens). log_lock_waits=on.
#  - pg_hba.conf: solo el rol de la app por TCP local (127.0.0.1 y ::1), sin
#    líneas de replicación; el superusuario solo por socket Unix (peer).
#  No toca listen_addresses (localhost) ni reinicia PostgreSQL: solo recarga.
set -euo pipefail

role="${1:-purgito_app}"
psql_pg() { sudo -u postgres psql -X -v ON_ERROR_STOP=1 "$@"; }

psql_pg <<SQL
ALTER ROLE ${role} SET idle_in_transaction_session_timeout = '5min';
ALTER SYSTEM SET log_min_duration_statement = '500ms';
ALTER SYSTEM SET log_parameter_max_length = 0;
ALTER SYSTEM SET log_lock_waits = on;
SQL

hba="$(psql_pg -At -c 'SHOW hba_file')"
if ! grep -qE "^host\s+all\s+all\s|^(local|host)\s+replication" "$hba"; then
    echo "pg_hba.conf ya está endurecido: $hba"
else
    cp -p "$hba" "$hba.pre-hardening.bak"
    python3 - "$hba" "$role" <<'PY'
import sys
path, role = sys.argv[1:3]
out = []
for line in open(path).read().split("\n"):
    f = line.split()
    if not f or f[0].startswith("#"):
        out.append(line)
    elif f[1:2] == ["replication"]:
        continue
    elif f[0] == "host" and f[1:3] == ["all", "all"]:
        out.append(f"host    all             {role:<15} {f[3]:<18} {f[4]}")
    else:
        out.append(line)
open(path, "w").write("\n".join(out))
PY
    echo "pg_hba.conf actualizado (copia en $hba.pre-hardening.bak)"
fi

psql_pg -At -c 'SELECT pg_reload_conf()' >/dev/null
echo "--- reglas activas"
psql_pg -At -c "SELECT type, database, user_name, address, auth_method, error FROM pg_hba_file_rules"
echo "--- parámetros"
psql_pg -At -c "SELECT name || ' = ' || setting FROM pg_settings WHERE name IN ('log_min_duration_statement','log_parameter_max_length','log_lock_waits','listen_addresses')"

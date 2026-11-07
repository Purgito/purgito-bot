#!/bin/bash
# Guardas de backup_db.sh (se "source"-ea; no se ejecuta solo): exclusión mutua, intervalo mínimo
# entre copias y trazabilidad del origen. Existen para que un `systemctl start purgito-backup`
# repetido (pruebas, mantenimiento) no suba a R2 un dump de ~62 MB que luego no se puede borrar
# hasta pasados los 6 días del Bucket Lock.
#
# Solo actúan con BACKUP_REQUIRE_GUARD=1 (lo pone purgito-backup.service). Sin eso (self-check,
# uso local, cron antiguo) backup_db.sh se comporta como siempre.
#
# Reglas, en este orden (salen con 75 = EX_TEMPFAIL; el servicio lo declara SuccessExitStatus,
# así que NO es un fallo ni dispara el aviso al Monitor, pero el log lo dice):
#   1. Otra copia en curso (flock sobre $BACKUP_DIR/.backup.lock): no arranca otra.
#   2. Ya hay una copia COMPLETA (subida y verificada) de hace menos de BACKUP_MIN_INTERVAL_HOURS
#      (12 por defecto): se omite. El timer de las 03:17 nunca choca con esto salvo que alguien
#      haya hecho una copia a mano en las 12 h previas, y entonces ese día ya está cubierto.
#   3. Para saltarse la regla 2 hay que pedirlo con deploy/backup_now.sh "motivo" --forzar. Ese script
#      deja $BACKUP_DIR/.manual-reason (0600, vale 5 min y se consume) con usuario, motivo y si se
#      fuerza: quien lanza una copia a mano queda en el log (también sin --forzar).
# Trazabilidad: cada corrida escribe una línea "BACKUP ORIGEN" (timer o manual, usuario, motivo).

GUARD_NO_RUN=75

# Segundos desde la última copia completa registrada en $1/.last-ok (vacío si no hay).
guard_last_ok_age() {
    local f="$1/.last-ok" ts
    [ -s "$f" ] || return 0
    ts="$(cat "$f" 2>/dev/null || true)"
    [[ "$ts" =~ ^[0-9]+$ ]] || return 0
    echo $(( $(date +%s) - ts ))
}

guard_mark_ok() { [ "${BACKUP_REQUIRE_GUARD:-0}" = "1" ] || return 0; date +%s > "$1/.last-ok"; }

# Lee y CONSUME el aviso de ejecución manual (si es reciente). Imprime "forzar|usuario|motivo" o nada.
guard_take_reason() {
    local f="$1/.manual-reason" ts user force reason
    [ -s "$f" ] || return 0
    IFS='|' read -r ts user force reason < "$f" || true
    rm -f -- "$f"
    [[ "$ts" =~ ^[0-9]+$ ]] || return 0
    [ $(( $(date +%s) - ts )) -le 300 ] || return 0
    echo "${force:-0}|${user:-?}|${reason:-sin motivo}"
}

# guard_enter DIR: devuelve 0 si la corrida puede seguir; 75 si se omite (ya registró por qué).
guard_enter() {
    local dir="$1" origin age min_s forced who why manual
    [ "${BACKUP_REQUIRE_GUARD:-0}" = "1" ] || return 0

    exec 9> "$dir/.backup.lock"
    if ! flock -n 9; then
        echo "$(date -Is) OMITIDO: ya hay una copia en curso (bloqueo $dir/.backup.lock)" >&2
        return "$GUARD_NO_RUN"
    fi

    if [ -n "${TRIGGER_UNIT:-}" ]; then origin="timer ($TRIGGER_UNIT)"; else origin="manual/otro"; fi
    manual="$(guard_take_reason "$dir")"
    forced=0
    if [ -n "$manual" ]; then
        IFS='|' read -r forced who why <<< "$manual"
        origin="$origin; MANUAL de $who: $why$([ "$forced" = 1 ] && echo ' (forzada)')"
    fi
    echo "$(date -Is) BACKUP ORIGEN: $origin"

    [ "$forced" != 1 ] || return 0
    min_s=$(( ${BACKUP_MIN_INTERVAL_HOURS:-12} * 3600 ))
    age="$(guard_last_ok_age "$dir")"
    if [ -n "$age" ] && [ "$age" -lt "$min_s" ]; then
        echo "$(date -Is) OMITIDO: ya hay una copia completa de hace $(( age / 60 )) min (mínimo $(( min_s / 3600 )) h entre copias). Para forzar una: sudo deploy/backup_now.sh \"motivo\" --forzar" >&2
        return "$GUARD_NO_RUN"
    fi
    return 0
}

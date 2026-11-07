#!/bin/bash
# Corrección mínima de la landing ya expuesta, SIN tocar el árbol que sirve nginx hasta que se pida.
#
# OBSOLETO desde la migración a releases (2026-11-07): nginx ya no sirve el árbol de trabajo, así que `apply` no
# publica nada. Sigue sirviendo `build` (staging provisional) para `publish_landing.sh publish --from-dir`.
# Antes de la migración, nginx servía /home/purgito/purgito-bot/landing y `apply --yes` publicaba al instante.
#
#   deploy/landing_hotfix.sh build           # construye en $STAGING (no toca el árbol servido)
#   deploy/landing_hotfix.sh diff            # qué archivos cambiarían en el árbol servido
#   deploy/landing_hotfix.sh apply --yes     # copia SOLO esos archivos al árbol servido (público al instante)
#   deploy/landing_hotfix.sh rollback --yes  # restaura los archivos aplicados desde la copia hecha por apply
#
# Qué corrige: docs/provisional/PRIVACY*.md (la Política tal como es cierta en producción hoy); ver
# docs/provisional/README.md. No toca nada más: el resto de la landing queda como está.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGING="${STAGING:-$HOME/purgito-release-staging}"
LIVE="${LIVE:-$repo/landing}"
BACKUP="${BACKUP:-$HOME/purgito-release-backups/hotfix-pre}"
cmd="${1:-}"; yes="${2:-}"

changed() { # archivos (relativos) distintos entre staging y el árbol servido
    rsync -rcn --itemize-changes --exclude '.*' "$STAGING/landing/" "$LIVE/" | awk '/^[<>c]f/ {print $2}'
}

case "$cmd" in
build)
    rm -rf "$STAGING"; mkdir -p "$STAGING"
    rsync -a --exclude '__pycache__' "$repo/landing" "$repo/docs" "$STAGING/"
    cp "$repo/docs/provisional/PRIVACY.md" "$repo/docs/provisional/PRIVACY.en.md" "$STAGING/docs/"
    ( cd "$STAGING" && python3 landing/build_docs.py ) >/dev/null
    ( cd "$STAGING" && python3 landing/build_docs.py --check )
    echo "construido en $STAGING (el árbol servido $LIVE NO se tocó)"
    ;;
diff)
    [ -d "$STAGING/landing" ] || { echo "ERROR: ejecuta primero 'build'" >&2; exit 1; }
    n=0; while IFS= read -r f; do echo "  cambiaría: $f"; n=$((n + 1)); done < <(changed)
    echo "$n archivo(s) distintos"
    ;;
apply)
    [ "$yes" = "--yes" ] || { echo "ERROR: esto publica al instante; repite con --yes (o usa 'diff' para ver qué cambia)" >&2; exit 2; }
    [ -d "$STAGING/landing" ] || { echo "ERROR: ejecuta primero 'build'" >&2; exit 1; }
    rm -rf "$BACKUP"; mkdir -p "$BACKUP"
    while IFS= read -r f; do
        [ -f "$LIVE/$f" ] && { mkdir -p "$BACKUP/$(dirname "$f")"; cp -p "$LIVE/$f" "$BACKUP/$f"; }
        mkdir -p "$LIVE/$(dirname "$f")"; cp -p "$STAGING/landing/$f" "$LIVE/$f"; echo "  aplicado: $f"
    done < <(changed)
    echo "copia de lo anterior en $BACKUP (deshacer: rollback --yes)"
    ;;
rollback)
    [ "$yes" = "--yes" ] || { echo "ERROR: repite con --yes" >&2; exit 2; }
    [ -d "$BACKUP" ] || { echo "ERROR: no hay copia en $BACKUP" >&2; exit 1; }
    ( cd "$BACKUP" && find . -type f ) | while IFS= read -r f; do cp -p "$BACKUP/$f" "$LIVE/$f"; echo "  restaurado: $f"; done
    ;;
*) echo "uso: landing_hotfix.sh build | diff | apply --yes | rollback --yes" >&2; exit 2 ;;
esac

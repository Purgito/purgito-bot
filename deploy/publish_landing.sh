#!/bin/bash
# Publicación de la landing por RELEASES: nginx sirve $BASE/current (un symlink), nunca el árbol de trabajo.
# Construir documentación, correr pruebas o editar archivos en el checkout NO cambia la web pública: solo
# `publish --yes` crea un release nuevo y mueve el symlink (atómico). Deshacer = repuntar el symlink.
#
#   deploy/publish_landing.sh publish [--ref REF | --from-dir DIR] [--yes]   # por defecto REF=HEAD; ensayo sin --yes
#   deploy/publish_landing.sh rollback [ID] --yes                            # al release anterior (o al ID)
#   deploy/publish_landing.sh list
#
# Origen: `--ref` usa SOLO lo commiteado (git archive): los cambios sin commit no se publican. `--from-dir DIR`
# espera DIR/landing y DIR/docs (p. ej. el staging de landing_hotfix.sh). Antes de publicar se ejecuta
# `build_docs.py --check` sobre esa copia: si el HTML no corresponde a docs/*.md, no se publica.
# Excluye del release lo que no es sitio (build_docs.py, tests .mjs, pages/ con las fuentes, notas de diseño).
#
# Variables: BASE (/var/www/purgito), KEEP (releases conservados, 5). Como root deja root:root; sin root (pruebas)
# usa el usuario actual. nginx: `root /var/www/purgito/current;` (ver DEPLOY.md § Releases de la landing).
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="${BASE:-/var/www/purgito}"
KEEP="${KEEP:-5}"
EXCLUDES=(--exclude '__pycache__' --exclude 'build_docs.py' --exclude '*.mjs' --exclude 'DESIGN_SYSTEM.md' --exclude '/pages')
die() { echo "ERROR: $*" >&2; exit 1; }
cmd="${1:-}"; shift || true

cur_id() { [ -L "$BASE/current" ] && basename "$(readlink "$BASE/current")" || true; }
releases() { [ -d "$BASE/releases" ] && ls -1 "$BASE/releases" | sort || true; }
point() { # repunta current de forma atómica
    ln -sfn "$BASE/releases/$1" "$BASE/.current.new" && mv -T "$BASE/.current.new" "$BASE/current"
}

case "$cmd" in
list)
    c="$(cur_id)"; releases | while IFS= read -r r; do [ "$r" = "$c" ] && echo "* $r (publicado)" || echo "  $r"; done
    ;;
publish)
    ref="HEAD"; from=""; yes=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --ref) ref="${2:-}"; shift 2 ;;
            --from-dir) from="${2:-}"; shift 2 ;;
            --yes) yes=1; shift ;;
            *) die "argumento desconocido: $1" ;;
        esac
    done
    tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
    if [ -n "$from" ]; then
        [ -d "$from/landing" ] && [ -d "$from/docs" ] || die "$from debe contener landing/ y docs/"
        rsync -a "$from/landing" "$from/docs" "$tmp/"; sha="dir"
    else
        git -C "$repo" rev-parse --verify "$ref^{commit}" >/dev/null 2>&1 || die "no existe la referencia $ref"
        git -C "$repo" archive "$ref" landing docs | tar -x -C "$tmp"
        sha="$(git -C "$repo" rev-parse --short "$ref")"
        [ -z "$(git -C "$repo" status --porcelain -- landing docs)" ] || echo "AVISO: hay cambios SIN commit en landing/ o docs/: NO se publican (solo $ref)." >&2
    fi
    for f in landing/index.html landing/es/privacidad/index.html landing/en/privacy/index.html landing/sitemap.xml; do
        [ -s "$tmp/$f" ] || die "falta $f en el origen"
    done
    ( cd "$tmp" && python3 landing/build_docs.py --check >/dev/null ) || die "build_docs.py --check falla: el HTML no corresponde a docs/*.md"
    id="$(date -u +%Y%m%dT%H%M%SZ)-$sha"
    echo "release $id desde ${from:-$ref} (comprobado con build_docs.py --check); actual: $(cur_id || true)"
    [ "$yes" = 1 ] || { echo "(ensayo: no se publicó nada; añade --yes)"; exit 0; }
    mkdir -p "$BASE/releases"
    rsync -a "${EXCLUDES[@]}" "$tmp/landing/" "$BASE/releases/$id/"
    chmod -R u+rwX,go+rX,go-w "$BASE/releases/$id"
    [ "$(id -u)" != 0 ] || chown -R root:root "$BASE/releases/$id"
    point "$id"
    echo "publicado: $BASE/current -> releases/$id"
    n="$(releases | wc -l)"
    if [ "$n" -gt "$KEEP" ]; then
        releases | head -n $((n - KEEP)) | while IFS= read -r old; do
            [ "$old" = "$(cur_id)" ] || { rm -rf "${BASE:?}/releases/$old"; echo "eliminado release antiguo: $old"; }
        done
    fi
    ;;
rollback)
    to=""; yes=0
    for a in "$@"; do case "$a" in --yes) yes=1 ;; *) to="$a" ;; esac; done
    c="$(cur_id)"
    if [ -z "$to" ]; then to="$(releases | grep -B1 -x "$c" | head -n1)"; [ -n "$to" ] && [ "$to" != "$c" ] || die "no hay un release anterior"; fi
    [ -d "$BASE/releases/$to" ] || die "no existe el release $to"
    echo "rollback: $c -> $to"
    [ "$yes" = 1 ] || { echo "(ensayo; añade --yes)"; exit 0; }
    point "$to"; echo "hecho"
    ;;
*) die "uso: publish_landing.sh publish [--ref REF | --from-dir DIR] [--yes] | rollback [ID] --yes | list" ;;
esac

#!/bin/bash
# Self-check de publish_landing.sh en un BASE temporal: sin root, sin nginx, sin tocar /var/www ni el árbol servido.
#   bash deploy/publish_landing_test.sh
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export BASE="$tmp/www" KEEP=2
fail() { echo "FAIL: $*"; exit 1; }
pub() { bash "$repo/deploy/publish_landing.sh" "$@"; }
cur() { basename "$(readlink "$BASE/current")"; }

mkdir "$tmp/src"; rsync -a --exclude __pycache__ "$repo/landing" "$repo/docs" "$tmp/src/"

# 1. Ensayo: no crea nada.
pub publish --from-dir "$tmp/src" | grep -q "ensayo" || fail "el ensayo debía avisar que no publicó"
[ ! -e "$BASE" ] || fail "el ensayo creó $BASE"

# 2. Publicar: symlink atómico, sin archivos de desarrollo, legible.
pub publish --from-dir "$tmp/src" --yes >/dev/null
r1="$(cur)"
[ -s "$BASE/current/index.html" ] && [ -s "$BASE/current/es/privacidad/index.html" ] || fail "release sin páginas"
for x in build_docs.py DESIGN_SYSTEM.md pages test_dash.mjs; do [ ! -e "$BASE/current/$x" ] || fail "el release contiene $x"; done
[ -z "$(find "$BASE/releases/$r1" -perm /022 -print -quit)" ] || fail "permisos de escritura de grupo/otros"

# 3. Aislamiento: tocar el árbol de desarrollo NO cambia lo publicado.
echo "<!-- local -->" >> "$tmp/src/landing/es/privacidad/index.html"
! grep -q "<!-- local -->" "$BASE/current/es/privacidad/index.html" || fail "un cambio local llegó al sitio"

# 4. HTML que no corresponde a docs/*.md: no se publica y el sitio sigue igual.
if pub publish --from-dir "$tmp/src" --yes >/dev/null 2>&1; then fail "publicó HTML desincronizado"; fi
[ "$(cur)" = "$r1" ] || fail "current cambió tras un intento fallido"
rsync -a "$repo/landing/" "$tmp/src/landing/"   # vuelve a un HTML coherente

# 5. Segundo release, rollback y poda por KEEP.
sleep 1; pub publish --from-dir "$tmp/src" --yes >/dev/null; r2="$(cur)"
[ "$r2" != "$r1" ] || fail "no hubo release nuevo"
pub rollback --yes >/dev/null; [ "$(cur)" = "$r1" ] || fail "el rollback no volvió al release anterior"
sleep 1; pub publish --from-dir "$tmp/src" --yes >/dev/null
[ "$(ls "$BASE/releases" | wc -l)" = 2 ] || fail "KEEP=2 no podó"
[ -d "$BASE/releases/$(cur)" ] || fail "se podó el release publicado"
echo "OK publish_landing_test"

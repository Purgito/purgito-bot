#!/bin/bash
# Ensayo AISLADO de purgito-vault: imagen LUKS desechable, contraseñas simuladas con archivos, sin tocar el
# volumen real, las unidades de systemd ni R2. Usa el servidor Tang real del host si responde.
# Uso (como root, desde el checkout): sudo bash tests/vault_rehearsal.sh
set -uo pipefail
TOOL="$(cd "$(dirname "$0")/.." && pwd)/deploy/purgito-vault.sh"
W="$(mktemp -d /var/tmp/pv-reh.XXXXXX)"; ok=0; bad=0
cleanup() { umount "$W/mnt" 2>/dev/null; cryptsetup close pvreh 2>/dev/null; rm -rf "$W"; }; trap cleanup EXIT
mkdir -p "$W/mnt" "$W/state" "$W/keys"
for r in unlock recovery; do head -c 24 /dev/urandom | base64 > "$W/keys/$r.key"; done
head -c 64 /dev/urandom > "$W/interim.key"
age-keygen -o "$W/age.txt" 2>/dev/null; RCP="$(age-keygen -y "$W/age.txt")"; echo "BACKUP_AGE_RECIPIENTS=$RCP" > "$W/backup.env"
truncate -s 64M "$W/vault.img"
cryptsetup luksFormat --type luks2 --pbkdf pbkdf2 --iter-time 50 --batch-mode --key-file "$W/interim.key" "$W/vault.img"
echo 0 > "$W/state/interim-keyslot"
cryptsetup open --key-file "$W/interim.key" "$W/vault.img" pvreh; mkfs.ext4 -q /dev/mapper/pvreh; mount /dev/mapper/pvreh "$W/mnt"
export PV_SKIP_GUARD=1 PV_SKIP_UNITS=1 PV_REHEARSAL_KEYS="$W/keys" PV_IMG="$W/vault.img" PV_MAPPER=pvreh PV_MNT="$W/mnt" \
       PV_STATE="$W/state" PV_KEYFILE="$W/interim.key" PV_BACKUP_ENV="$W/backup.env" PV_BINDS="" PV_SERVICES="" \
       PV_TANG_THP_FILE="${PV_TANG_THP_FILE:-/var/lib/purgito-vault/tang.thp}"
t() { local name="$1"; shift; if "$@" >"$W/out.txt" 2>&1; then echo "  [ok]   $name"; ok=$((ok+1)); else echo "  [FALLO] $name"; sed 's/^/           /' "$W/out.txt" | tail -4; bad=$((bad+1)); fi; }
nt() { local name="$1"; shift; if "$@" >"$W/out.txt" 2>&1; then echo "  [FALLO] $name (debía fallar)"; bad=$((bad+1)); else echo "  [ok]   $name (falló como debe)"; ok=$((ok+1)); fi; }
V() { bash "$TOOL" "$@"; }
echo "== Fase 1: inscripción por fases (no destruye nada hasta 'retire')"
t "enroll add"      V enroll add
t "enroll verify"   V enroll verify
nt "retire sin age-verify se rechaza" V enroll retire --yes
t "age-canary"      V age-canary
TOK="$(age -d -i "$W/age.txt" "$W/state/age-canary.age" | sed 's/.*://')"
t "age-verify"      env PV_REHEARSAL_AGE_TOKEN="$TOK" bash "$TOOL" age-verify
t "la provisional AÚN abre antes de retire" cryptsetup open --test-passphrase --key-file "$W/interim.key" "$W/vault.img"
echo "== Fase 2: retire (respaldo, revoca, re-comprueba, respaldo definitivo)"
t "enroll retire --yes" V enroll retire --yes
nt "la provisional YA NO abre"              cryptsetup open --test-passphrase --key-file "$W/interim.key" "$W/vault.img"
t "contraseña de desbloqueo sigue abriendo"  cryptsetup open --test-passphrase --key-file "$W/keys/unlock.key" "$W/vault.img"
t "contraseña de recuperación sigue abriendo" cryptsetup open --test-passphrase --key-file "$W/keys/recovery.key" "$W/vault.img"
FH="$(ls -1t "$W"/state/luks-header-final-*.img.age | head -1)"
age -d -i "$W/age.txt" "$FH" > "$W/final.hdr"
nt "el respaldo definitivo NO permite la provisional" cryptsetup open --test-passphrase --header "$W/final.hdr" --key-file "$W/interim.key" "$W/vault.img"
t  "el respaldo definitivo SÍ abre con las nuevas"    cryptsetup open --test-passphrase --header "$W/final.hdr" --key-file "$W/keys/unlock.key" "$W/vault.img"
[ -e "$W/interim.key" ] && { echo "  [FALLO] el archivo de la provisional sigue existiendo"; bad=$((bad+1)); } || { echo "  [ok]   archivo de la provisional destruido"; ok=$((ok+1)); }
echo "== Fase 3: desbloqueo automático por Tang (solo si el servidor responde)"
if curl -fsS -m 6 -o /dev/null http://10.203.0.1:7500/adv 2>/dev/null && [ -s "$PV_TANG_THP_FILE" ]; then
  t  "tang-bind (solo añade una ranura)" V tang-bind
  t  "tang-test"                          V tang-test
  t  "hay 3 ranuras: 2 de contraseña + 1 de Tang" test "$(cryptsetup luksDump "$W/vault.img" | grep -cE '^ *[0-9]+: luks2')" = 3
  umount "$W/mnt"; cryptsetup close pvreh
  t  "open --auto abre SIN contraseña"    V open --auto
  t  "tras abrir, el volumen está montado" mountpoint -q "$W/mnt"
  t  "tang-unbind deja solo 2 ranuras" bash -c "bash '$TOOL' tang-unbind && test \"\$(cryptsetup luksDump '$W/vault.img' | grep -cE '^ *[0-9]+: luks2')\" = 2"
  nt "open --auto ya no funciona sin Tang enlazado" V open --auto
else echo "  (se omite: Tang no responde o falta $PV_TANG_THP_FILE)"; fi
echo "== Fase 4: ensayo de borrado (solo plan)"
t "wipe-plaintext --plan no cambia nada" V wipe-plaintext --plan
echo; echo "RESULTADO: $ok correctas, $bad fallidas"; [ "$bad" = 0 ]

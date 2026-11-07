# Despliegue coordinado: privacidad, logs, backups y textos públicos

**Léelo entero antes de empezar.** Cada paso marca si es reversible. Las acciones sobre logs o copias
(pasos 3 y 6) son irreversibles y requieren autorización expresa del titular. Verificación de solo lectura:
`sudo deploy/verify_privacy_release.sh pre|post [--web]`.

> **Estado (2026-11-07, 19:5x UTC): migración hecha.** nginx sirve `/var/www/purgito/current` (release
> `20261107T195651Z-dir`, construido desde el staging provisional: Política v2.2.1). El árbol de trabajo
> `landing/` ya NO es público; `build_docs.py` puede ejecutarse en él sin efecto en producción. El `root` anterior
> está en `/etc/nginx/purgito.conf.pre-releases-20261107` (rollback: restaurarlo y `nginx -t && systemctl reload nginx`).
> La Política objetivo (v2.3, `docs/PRIVACY*.md`) se publica con el paso 7, no antes.

## A. Contención inmediata y aislamiento definitivo (primero; requiere autorización)
1. **Corregir lo que ya es público** (solo las afirmaciones aún no ciertas; `docs/provisional/`):
   ```bash
   deploy/landing_hotfix.sh build     # construye aparte (~/purgito-release-staging); no toca lo público
   deploy/landing_hotfix.sh diff      # debe listar solo es/privacidad y en/privacy
   deploy/landing_hotfix.sh apply --yes   # PUBLICA al instante; guarda lo anterior; 'rollback --yes' lo deshace
   ```
   Si se hace el paso 2 de inmediato, este `apply` es innecesario: el primer release se construye ya desde el staging corregido.
2. **Aislar desarrollo de producción** (nginx deja de servir el árbol de trabajo):
   ```bash
   sudo install -d -m 0755 /var/www/purgito
   sudo deploy/publish_landing.sh publish --from-dir ~/purgito-release-staging --yes   # primer release (= lo público corregido)
   # /etc/nginx/conf.d/purgito.conf, server de purgito.app:  root /var/www/purgito/current;
   sudo nginx -t && sudo systemctl reload nginx
   curl -sI https://purgito.app/es/privacidad/ | head -1      # 200
   ```
   Desde entonces solo `publish_landing.sh publish --yes` cambia lo público (usa lo **commiteado** con `--ref`, o un
   directorio de staging con `--from-dir`), y `rollback --yes` repunta el symlink. Rollback de este cambio:
   restaurar `root /home/purgito/purgito-bot/landing;` y recargar nginx.
3. Con eso, `build_docs.py`, las pruebas y las ediciones locales ya no afectan a la web.

## Grupos de commits (en este orden de despliegue)
| # | Grupo | Contenido | Se despliega con |
|---|---|---|---|
| 1 | `fix(r2): dns pin` | `src/r2.py` | `git pull` + reinicio del bot |
| 3 | `feat(backups)` | runner, guardas, ledger adelgazado, vigilancia | `install_backup_runner.sh` |
| 4 | `feat(logs)` | `RetainedFileHandler`, filtro de query, `nginx-logging.conf`, `scrub_oauth_logs.py` | `git pull` + reinicio + nginx |
| 2 | `docs(legal)` | PRIVACY/TERMS/REFUNDS/NOVEDADES, Premium, páginas generadas, `docs/provisional/`, `landing_hotfix.sh` | `publish_landing.sh` (paso 7) |
| 4b | `feat(deploy)` | `publish_landing.sh`, su test, guarda de `build_docs.py`, DEPLOY.md | mismo commit que el 4 o aparte |

## 0. Antes de tocar nada (solo lectura)
- `sudo deploy/verify_privacy_release.sh pre` y guarda la salida: es la línea base.
- **Dashboard de Cloudflare** (el token no las puede leer): Bucket Lock 6 d en `gen2/purgito-`; lifecycle
  13 d en `gen2/purgito-` y 14 d en `gen2/ledger/`; **sin** lock en `gen2/ledger/` ni lifecycle en
  `luks-header`/`secretos`; lock 14 d en la raíz (gen1). Apunta lo que haya.
- Probar `contacto@purgito.app` desde fuera. Tener decidido el nombre del responsable y la base de licitud
  (`docs/LEGITIMIDAD_APRENDIZAJE.md`). **Sin eso no se ejecuta el paso 7.**

## 1. Código (reversible: `git revert` + reinicio)
`git pull` de los grupos 1 y 4 → `sudo systemctl restart bot-purg`. Al arrancar, `logging_setup` recorta los
logs heredados (> `LOG_RETENTION_DAYS` = 30). Comprobar `journalctl -u bot-purg -n 30`.

## 2. nginx (reversible: quitar el `include` y recargar)
```bash
sudo install -m 0644 deploy/nginx-logging.conf /etc/nginx/conf.d/00-purgito-logging.conf
# en /etc/nginx/nginx.conf: access_log /var/log/nginx/access.log purgito;
sudo nginx -t && sudo systemctl reload nginx
sudo logrotate -f /etc/logrotate.d/nginx      # el access.log antiguo pasa a access.log.1 (ya no es el activo)
```

## 3. Sanear logs históricos (IRREVERSIBLE: requiere autorización)
Solo cambia el VALOR de `code`, `state`, tokens…; conserva línea, hora, ruta, estado y navegador.
```bash
sudo python3 -I scripts/scrub_oauth_logs.py /var/log/nginx/access.log.* /var/log/nginx/error.log.* data/bot.log.*   # ensayo
sudo python3 -I scripts/scrub_oauth_logs.py --apply --report /root/scrub-informe.json <los mismos archivos>
sudo python3 -I scripts/scrub_oauth_logs.py /var/log/nginx/access.log.* data/bot.log.*   # debe decir "sin parámetros sensibles"
```
- Se niega a tocar archivos activos o modificados hace < 2 min. El informe (0600) lista archivo, líneas y
  nombres de parámetros, nunca valores; es la evidencia de que hubo callbacks OAuth.
- No deja `.bak`. Los bloques liberados del disco raíz pueden conservar el original hasta reutilizarse:
  no es un borrado forense (el volumen cifrado sí está cubierto).
- Ya hay 14 archivos de nginx y `bot.log.1/.2` afectados (ensayo del 7 nov: ver `verify`).

## 4. Backups (reversible salvo la primera poda del registro)
```bash
sudo deploy/install_backup_runner.sh --recipient <age1…> --apply   # exige commits en HEAD; conserva drop-ins
sudo /opt/purgito-backup/deploy/backup_task.sh preflight
.venv/bin/python scripts/r2_backup.py prune-ledger                 # ensayo; ~130 a conservar
```
Con autorización: habilitar `purgito-backup-check.timer` y `purgito-vault-watch.timer`; añadir la unidad
`purgito-vault-watch.service` a la config del agente de Purgito Monitor (`kind: systemd`). La primera pasada
real de `prune-ledger` borra hasta 300 objetos (≈14 pasadas de 5 min): **IRREVERSIBLE**, requiere autorización.
Tras el apagado de la VM: `sudo /opt/purgito-backup/deploy/backup_now.sh "tras apagado"`.

## 5. Reglas de Cloudflare (a mano, con autorización)
Ver `docs/POSTGRES.md` § Reglas. Gen1 (4 objetos de la raíz): se borran a partir del 19 nov 2026.

## 6. Verificar antes de publicar
`sudo deploy/verify_privacy_release.sh post` debe terminar en `TODO OK`. Cualquier `FALTA` bloquea el paso 7:
la Política afirma logs a 30 días, nginx sin parámetros, guardas de restauración y poda local por edad.

## 7. Publicar los textos objetivo (grupo 2)
Con los grupos commiteados y el paso 6 en `TODO OK`:
`sudo deploy/publish_landing.sh publish --ref <commit> ` (ensayo) y luego con `--yes`. Después
`sudo deploy/verify_privacy_release.sh post --web`. Retirarlos: `sudo deploy/publish_landing.sh rollback --yes`.

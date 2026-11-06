# Cifrado en reposo (P0): qué hay, cómo se usa y cómo se recupera

**Estado a 2026-11-06: implementado y desplegado; el P0 sigue ABIERTO hasta completar tres pasos que solo puede
hacer el titular** (contraseñas, comprobación de desbloqueo y borrado de las copias en claro). Lo mide
`sudo deploy/check_encryption_at_rest.sh`: sale con código 0 únicamente cuando todo está cifrado, no quedan
restos en claro y la clave provisional ya no existe.

## Qué se implementó

Esta VM tiene un solo disco virtual (`vda`, sin espacio libre sin particionar), así que el volumen
independiente es un **contenedor LUKS2 en un archivo** (`/var/lib/purgito-vault/vault.img`, 8 GiB reservados,
aes-xts-plain64, Argon2id con 256 MiB por la poca RAM). Se montó en `/srv/purgito` y desde ahí se
superponen (bind) las rutas sensibles sin cambiar ninguna configuración. No se modificó ninguna partición.

| Qué | Dónde queda |
|---|---|
| PostgreSQL y su **WAL** (`/var/lib/postgresql`), logs de PostgreSQL | volumen cifrado |
| Secretos: `.env` del bot, `/etc/purgito/*.env`, token del túnel (`/etc/cloudflared`) | volumen cifrado |
| Datos y logs del bot (`data/`, incluye el latido de la guardia de privacidad) | volumen cifrado |
| Copias locales de backup y copias antiguas (incluidos CSV en claro de octubre con `gif_senders` y apodos) | volumen cifrado |
| **Swap** (2 GiB) | dm-crypt con clave aleatoria nueva en cada arranque (`purgito-cryptswap.service`); el archivo en claro se sobrescribió con ceros |
| Logs del sistema | journald en RAM (`Storage=volatile`) y **sin reenvío a syslog** (`ForwardToSyslog=no`); los `syslog*`, los volcados de `/var/crash` y el journal persistente anterior se sobrescribieron |
| `/tmp` del bot | ya era `tmpfs` (RAM) |

Sin el volumen abierto **no arrancan** PostgreSQL, el bot, Studio, el túnel ni los backups
(`ConditionPathIsMountPoint=/srv/purgito`): fallan "limpio", no en bucle. Consecuencia asumida: tras un
reinicio **la web y el bot están caídos hasta que alguien teclee la contraseña** (el túnel también depende del
volumen). El agente de monitoreo sigue vivo fuera del volumen y avisa.

## Uso diario y recuperación

    sudo purgito-vault status            # estado, sin cambiar nada
    sudo purgito-vault open              # tras un reinicio: pide la contraseña, monta y arranca todo
    sudo purgito-vault close             # para servicios, desmonta y cierra
    sudo purgito-vault header-backup     # nuevo respaldo del encabezado (tras cambiar contraseñas)

Los comandos se ejecutan desde la copia de root `/opt/purgito-vault` (el checkout del bot lo puede modificar el
usuario del bot). Las contraseñas las pide `cryptsetup` directamente en tu terminal: no pasan por argumentos,
variables ni archivos del script. **No ejecutes `enroll` ni `open` desde un asistente**: entra por SSH.

### Contraseñas, copia offline y encabezado (lo hace `enroll`, una vez)

`sudo purgito-vault enroll` (en tu SSH) te pide, sin eco: (1) contraseña de **desbloqueo**, (2) contraseña de
**recuperación** (distinta), las comprueba tecleándolas de nuevo, **destruye la clave provisional** y verifica
que ya no abre el volumen. Después hace `luksHeaderBackup`, lo cifra con age (clave pública nueva de
`backup.env`) y lo sube a R2 como `gen2/luks-header-<fecha>.img.age`; copia local cifrada en
`/var/lib/purgito-vault/`. El respaldo del encabezado se hace **después** de fijar las ranuras: uno anterior
restauraría la clave provisional.

Guarda ambas contraseñas en la bóveda "Purgito" de Proton Pass **y** la de recuperación offline (papel).
**Si pierdes las dos, el volumen es irrecuperable.** Aun así los datos no se pierden: los respaldos diarios en R2
están cifrados con la clave age (independiente) y se restauran en una base nueva (`docs/POSTGRES.md`).

| Situación | Qué hacer |
|---|---|
| Reinicio | `sudo purgito-vault open` y la contraseña de desbloqueo |
| Olvidaste la de desbloqueo | `open` con la de recuperación; después añade otra con `cryptsetup luksAddKey` y `header-backup` |
| Encabezado dañado | Bajar `gen2/luks-header-*.img.age` de R2, descifrar con la clave age privada y `cryptsetup luksHeaderRestore` |
| Perdiste todo acceso al volumen | Restaurar el último dump de R2 en una base nueva y reconciliar (`docs/POSTGRES.md`) |
| Disco lleno | El contenedor está reservado entero (no crece solo); la raíz conserva ≥ 3 GiB libres |

## Estado verificado en producción (2026-11-06)

- Migración con servicios parados, copia con `rsync` y comparación `diff` capa original vs volumen antes de
  arrancar; PostgreSQL con 63 objetos y el corpus íntegro; bot, Studio y túnel sirviendo; `https://purgito.app`
  responde.
- Prueba de recuperación con servicios reales: `close` (nada arranca, la web da 530), intento de arrancar sin el
  volumen **rechazado** por la condición, `open` y recuperación completa, con la guardia aceptando la base.
- Respaldo cifrado nuevo antes de migrar (`purgito-20261106-003222.dump.age`, 58 tablas, verificado).
- La copia original en claro **sigue debajo** de cada montaje: es la marcha atrás hasta el último paso.

## Qué falta para cerrar el P0 (solo el titular)

1. `sudo purgito-vault enroll` (arriba). El comprobador marcará `PROVISIONAL` e `INSUFICIENTE` hasta entonces.
2. **Ensayo de desbloqueo con tus contraseñas**: `sudo purgito-vault close && sudo purgito-vault open`, y mejor un
   reinicio real de la VM (la web estará caída hasta que teclees la contraseña).
3. `sudo purgito-vault wipe-plaintext --yes`: sobrescribe y borra las copias en claro que quedaron debajo. Es
   irreversible y solo se permite cuando ya no existe la clave provisional.
4. `sudo deploy/check_encryption_at_rest.sh` debe salir con código 0. Ese es el criterio de cierre.

## Limitaciones honestas

- Protege **en reposo**: una snapshot, una copia de la imagen o un disco sin la contraseña. No protege de quien
  tenga root en la VM **con el volumen abierto**.
- El contenedor es un archivo en la raíz sin cifrar: el tamaño y la existencia del volumen son visibles.
- Las credenciales de infraestructura que quedan fuera del volumen a propósito: el secreto del agente de
  monitoreo (`/etc/umbrel-monitor-agent/secret`, **pendiente de rotar**: se mostró por error en una conversación
  el 2026-11-05; el agente debe seguir vivo con el volumen cerrado para avisar) y la configuración SSH/Tailscale.
- Cifrar en el host (Renas) no se hizo ni se necesita; si se añadiera, sería una capa extra, no un sustituto.

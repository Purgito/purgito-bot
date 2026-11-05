# Cifrado en reposo (P0): estado, opciones y criterio de cierre

**Estado a 2026-11-05: ABIERTO. Nada está cifrado en reposo dentro de la VM.** Solo los *respaldos* salen
cifrados (age) antes de subir a R2; la política pública no afirma otra cosa. No se ha cambiado nada en
producción por este documento.

## Hechos verificados (solo lectura)

`deploy/check_encryption_at_rest.sh` (código 1 mientras algo esté en claro) en `purgito-vm`, 2026-11-05:

| Qué | Dónde | Estado |
|---|---|---|
| Datos de PostgreSQL (~0,9 GB, incluye el corpus de mensajes) | `/var/lib/postgresql/18/main` en `/dev/vda1` (ext4) | EN CLARO |
| Secretos: `.env` del bot, `/etc/purgito/*.env` (tokens R2, claves) | `/dev/vda1` | EN CLARO |
| Copias locales de backup | `/var/backups/purgito` | EN CLARO (los `.age` sí van cifrados) |
| Swap (2 GB, puede contener texto de mensajes) | `/swapfile` en `/dev/vda1` | EN CLARO |

`/etc/crypttab` está vacío, no hay dispositivos dm-crypt y no se detecta vTPM. La VM es KVM sobre un host
Umbrel que gestiona otra persona (Renas). Lo que haga el host no se ve desde dentro de la VM.

## Qué amenaza se quiere cubrir

1. **Copias de la imagen de disco o snapshots** que salgan del host (la snapshot que se pide a Renas es una
   copia completa en claro de la base y de los secretos).
2. **Robo o reutilización de discos físicos** del host.
3. Fuera de alcance: alguien con acceso root a la VM *en marcha* (el volumen está desbloqueado) o un fallo de
   la aplicación. El cifrado en reposo no protege de eso.

Consecuencia importante: una clave guardada **en el mismo disco** cifrado no protege de (1). La clave tiene
que vivir fuera de la imagen.

## Lección del incidente de LUKS (2026-11-05)

El primer intento perdió claves y datos. Cualquier plan nuevo exige, antes de tocar nada: (a) frase de
recuperación en la bóveda del titular **y** copia offline; (b) copia del encabezado LUKS (`cryptsetup
luksHeaderBackup`) cifrada con age y guardada con Bucket Lock; (c) **ensayo de desbloqueo y de restauración**
sobre un volumen nuevo y vacío; (d) snapshot confirmada; (e) no convertir en sitio el disco que ya contiene
los datos.

## Opciones

| Opción | Cubre (1) | Cubre (2) | Coste / riesgo |
|---|---|---|---|
| **A. Volumen de datos aparte con LUKS** (segundo disco virtual) para PostgreSQL, secretos, copias locales y swap; clave **ligada a la red** (Clevis + Tang en otra máquina, p. ej. el host Umbrel) con frase de recuperación | Sí | Sí | Reinicio sin intervención mientras Tang responde; si no, hay que teclear la frase. Requiere que Renas añada un disco y que exista Tang. Migración de PostgreSQL con `pg_dump`/restauración, sin conversión en sitio. |
| B. Igual que A pero **frase a mano** en cada arranque | Sí | Sí | Máxima simplicidad y seguridad, peor disponibilidad: un corte de luz deja el servicio caído hasta que alguien teclee. |
| C. Cifrado **en el host** (imagen sobre ZFS/LUKS del host) | No (el snapshot exportado sale descifrado) | Sí | Transparente para la VM; depende por completo de Renas y no es comprobable desde dentro. |
| D. Cifrado de aplicación (columnas del corpus) | Parcial | Parcial | Mucho cambio, gestión de claves en el propio proceso, no cubre swap ni secretos. No recomendado ahora. |

**Recomendación: A** (con B como respaldo manual). Es la única que cubre snapshots y discos, se puede ensayar sin
tocar producción y se comprueba desde dentro de la VM. C puede sumarse, pero no sustituye a A.

Los **secretos** (`.env`, `/etc/purgito`) y el **swap** también tienen que quedar en el volumen cifrado (enlace
o montaje), o seguirán en claro en la raíz. El swap puede cifrarse con clave aleatoria por arranque.

## Criterio de cierre (cuándo SÍ se puede marcar resuelto)

Todas, con evidencia guardada:

1. `deploy/check_encryption_at_rest.sh` sale con código 0 en producción: PostgreSQL, secretos, copias locales y
   swap sobre dispositivo `crypt`.
2. **Prueba del canario** (para el caso de que el host también cifre): escribir una cadena aleatoria única en un
   archivo de la base, hacer snapshot, y comprobar desde el host que la cadena **no** aparece en la imagen.
3. Reinicio real de la VM: arranca, PostgreSQL y el bot funcionan, y se anota si fue sin intervención o con frase.
4. Ensayo de recuperación: abrir el volumen desde cero con la frase de recuperación y con la copia del
   encabezado, en una máquina distinta.
5. Los respaldos siguen funcionando (`purgito-backup`) y el siguiente restore de prueba pasa.
6. `SECURITY.md` y `docs/PRIVACY*.md` describen lo que realmente existe (hoy `SECURITY.md` ya dice que no se cifra).

## Pasos propuestos (cada uno requiere autorización expresa; ninguno se ha ejecutado)

1. Decidir A o B y quién aloja Tang. Pedir a Renas el disco adicional (≥ 10 GB) y confirmar la snapshot.
2. En la VM: crear LUKS en el disco nuevo, probar apertura/cierre, guardar frase y copia del encabezado.
3. Montar, restaurar una copia de prueba de PostgreSQL ahí y validar (57 tablas) **sin tocar** la base viva.
4. Ventana de mantenimiento: parar bot, `pg_dump` final, mover `data_directory` y secretos, arrancar, validar.
5. Mantener el disco antiguo intacto hasta pasar el criterio de cierre; borrarlo solo con autorización.

Marcha atrás en cualquier paso: volver a apuntar `data_directory` al directorio original (sigue intacto).

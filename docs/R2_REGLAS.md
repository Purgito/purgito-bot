# Reglas de Bucket Lock y Lifecycle de `purgito-backups` (a configurar en el dashboard de Cloudflare)

El token de backups **no puede leer ni escribir estas reglas** (`AccessDenied`, comprobado el 2026-11-07): se
crean y se verifican a mano en *R2 → purgito-backups → Settings*. Los prefijos son literales desde el inicio de
la key: `purgito-` solo alcanza a `purgito-…` en la raíz (generación 1), nunca a `gen2/purgito-…`.

## Bucket Lock (antiborrado)
| Prefijo | Retención | Segundos | Protege |
|---|---|---|---|
| `gen2/purgito-` | **6 días** | 518 400 | dumps vigentes de un borrado masivo. Más de 6 haría fallar la poda diaria (HTTP 409 `ObjectLockedByBucketPolicy`) |
| `purgito-` | **14 días** | 1 209 600 | dumps de generación 1 (raíz) |
| `luks-header` | **14 días** | 1 209 600 | cabecera LUKS de generación 1 (raíz) |
| `privacy-prefs` | **14 días** | 1 209 600 | preferencias de generación 1 (raíz) |

Nunca un lock sin prefijo, ni indefinido, ni de más de 14 días, ni sobre `gen2/ledger/`, `gen2/luks-header-` o
`gen2/secretos-` (la poda del registro y del servidor necesitan poder borrar).

## Object Lifecycle (borrar al cumplirse la edad)
| Prefijo | Edad | Segundos | Función |
|---|---|---|---|
| `gen2/purgito-` | **13 días** | 1 123 200 | tope de la política si el servidor no corre. 13 y no 14: el proveedor borra con retraso (ver abajo) |
| `gen2/ledger/` | **14 días** | 1 209 600 | idem para el registro de eliminaciones (lápidas de 15 días). Expira **después** que los dumps |
| `purgito-`, `luks-header`, `privacy-prefs` (raíz, gen1) | 14 días | 1 209 600 | opcional: que la generación 1 caduque sola. Si no se crea, hay que borrarla a mano a partir del 19 nov 2026 |

**No** crear lifecycle sobre `gen2/luks-header-` ni `gen2/secretos-`: borraría también la única cabecera o paquete
vigente. Se podan a mano conservando siempre el último.

## Qué podemos y qué no podemos afirmar (documentación de Cloudflare)
- El Bucket Lock **prevalece** sobre el lifecycle: un objeto bloqueado no se borra antes de que termine el bloqueo.
- El lifecycle borra «típicamente dentro de las 24 horas» posteriores a la expiración: **no es un plazo exacto** y
  en objetos ya existentes puede tardar más. Por eso: 13 d para los dumps (peor caso real ≈ 14 d) y la Política
  habla de un límite «mientras el servicio funcione con normalidad», no de una garantía de borrado puntual.
- Si el registro expirara antes que un dump (por el desfase del proveedor), `reapply_deletions.py` exige
  `--sin-registro`: falla de forma explícita, no restaura en silencio (`tests/test_outage_compat.py`).

## Verificación (cada vez que se cambie algo)
1. Dashboard: captura o exportación de las reglas; comparar con las tablas de arriba.
2. `sudo /opt/purgito-backup/deploy/backup_task.sh preflight` (la poda no debe proponer borrar nada fuera de `gen2/`).
3. A los 14 días de la configuración: comprobar que la generación 1 desapareció (o borrarla a mano).

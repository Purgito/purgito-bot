# Validación local de Purgito Studio

Registro de la validación del desarrollo de Studio (3–4 de noviembre de 2026), sobre
la base `59aca3212ac7488e084f52d8ed3f9531761666d6`. Las secciones posteriores a la
primera describen las revisiones sucesivas; las cifras vigentes son las de «Ejecución final».

## Entorno y alcance

- Python 3.14.10 y PostgreSQL 18.6 reales, en contenedores desechables de desarrollo.
- Base `purgito_test`, red privada y credenciales exclusivamente de pruebas.
- No se inició el bot con Discord, no se consultó la base productiva y no se
  modificó la instalación en ejecución.
- El compose de `studio/development.compose.yml` construye Python y clientes
  PostgreSQL 18; su base usa tmpfs y no publica puertos.

## Pruebas

La suite completa final, construida y ejecutada desde el Compose documentado,
pasó con **2275 tests y 22 omitidos** en 64,07 s. Una omisión es Chromium, que no
se instala en la imagen básica de tests; se comprobó por separado con Playwright
1.64.1 y Chromium en el contenedor de desarrollo: **11 tests enfocados pasaron**,
incluidas las pruebas del navegador, reinicio abrupto y desconexión del gateway.
Las otras 21 omisiones corresponden a la suite existente. Los logs de la ejecución
final quedan en `data/studio-validation-full.log` y `data/studio-validation-focused.log`,
ignorados por Git.

La primera ejecución del Compose con salida de red totalmente deshabilitada
expuso 17 fallos en tests existentes de GIFs que necesitan resolución DNS antes de
sus respuestas HTTP simuladas. Se corrigió el entorno de tests dando salida solo
al contenedor de tests; la base permanece en red interna. No se cambió código de
GIFs para sortear esas comprobaciones y la suite completa volvió a pasar.
Los tests de Studio comprueban agregación, histogramas, medias ponderadas,
comparación entre períodos, actividad frente a entregas automáticas, adopción,
cohortes con retorno tras cambio de versión y censura de ventanas incompletas.
También comprueban limpieza de tablas y presencia asociada, reintento después de
commit ambiguo sin duplicación, rotación accidental de clave rechazada, reapertura
de conexiones y persistencia después de `os._exit()` en otro proceso.
La desconexión del gateway crea un hueco de cobertura incluso si el proceso vive.

La prueba real de Chromium usa endpoints aiohttp y PostgreSQL de pruebas:
siete vistas, estados vacíos, filtros y comparación personalizada, guardado y
recarga de notas, renderizado literal de HTML malicioso, ausencia de credenciales
en localStorage, ausencia de errores JS y ancho móvil sin desbordamiento.
La API comprueba credenciales, acceso loopback, Host, cabeceras proxy y escrituras.

Ruff (check y format), tests JS existentes de idioma/dashboard/historial,
`node --check studio/studio.js`, generación de documentación y `git diff --check`
pasaron. Los avisos de deprecación de dependencias no son fallos de las pruebas.

## Coste medido y límites

Benchmark sintético: **20.000 eventos**, **1,567 µs/evento** incluyendo el bucle,
126 claves agregadas pendientes, cero descartes. Solo mide `record()` en memoria;
no incluye SQL, envío a Discord, flush ni carga productiva real.
Se puede repetir con `scripts/benchmark_studio.py`.

No se ha probado un PostgreSQL instalado nativamente como servicio del host,
un corte eléctrico del host, ni una carga real del bot. Un corte puede perder los
agregados aún en memoria desde el último flush; los lotes confirmados sobreviven y
la cobertura posterior no se rellena. Las funciones sin adaptador ni comandos
registrados se muestran sin instrumentar, no como adopción cero.
La retención se ejecuta cuando el worker está activo; backups tienen su propia
política. Instalar, habilitar y comprobar recepción real requiere revisión y
aprobación del propietario.

Las capturas `data/studio-preview-empty.png` y `data/studio-preview-mobile.png`
son del estado vacío de pruebas, están ignoradas por Git y no simulan actividad.

## Revisión de continuación (3 de noviembre de 2026, segunda sesión)

- Entorno distinto al descrito arriba: host sin Docker accesible y con el `.venv`
  inservible (su intérprete solo existe dentro del contenedor). Se usó un venv y un
  PostgreSQL 18.6 desechables fuera del repositorio, con Python 3.13.5. Solo se ejecutó
  `tests/test_studio.py` (11 tests, todos correctos). **No se repitió** la suite completa
  de 2275 tests, ni Chromium, ni la medición en contenedor: sus resultados siguen siendo
  los del registro anterior, sin reverificar. Ruff (check y format) y `node --check` pasaron.
- Defecto corregido: cada ciclo de 10 s insertaba una fila de ledger aunque no hubiera
  datos (~8.640 al día) y reescribía la presencia diaria completa. Ahora un lote vacío no
  usa ledger y el inventario solo se escribe si cambió (test
  `test_idle_flushes_do_not_churn_ledger_or_presence`, que falló antes del arreglo).
- Coste medido contra PostgreSQL real: ciclo con 3.000 claves agregadas e inventario de
  200 servidores ≈ 50 ms (en el worker, fuera del camino de los comandos); ciclo en reposo
  ≈ 0,2 ms. `record()` ≈ 1,2 µs por evento (benchmark sintético repetido).

## Tercera sesión: cobertura, retención, errores y línea base

Entorno: igual que la sesión anterior (PostgreSQL 18.6 desechable, Python 3.13.5, fuera
del repositorio), con Chromium (Playwright) esta vez sí disponible.

Cambios y su evidencia:

- **Política de cobertura/comparación** (`report.py`, `model.py`). Pruebas: umbrales
  exactos (99,5 / 90 %), un reinicio de 90 s sigue `comparable` con el hueco cuantificado,
  un hueco de 2 días da `partial` y uno de 5 días `not_comparable` sin diferencia ni
  porcentaje (lo observado sigue visible), descartes degradan una cobertura del 100 % a
  `partial`, y sin sesiones la cobertura es 0 (nunca un cero de uso).
- **Retención agrupada.** Misma definición y mismos resultados: el algoritmo original
  se conserva como referencia ejecutable (`tests/studio_retention_reference.py`) y la
  prueba compara ambos sobre 16 combinaciones de ventana y filtros de versión/función,
  con datos sembrados que incluyen un hueco de 6 h, una sesión con descartes, un día
  sin inventario, inactivos y el límite de 90 días. Resultado idéntico, con elegibilidad
  verdadera y falsa ejercitadas. Consultas: **492 → 44** en total (de ~31 a 3 por
  informe); tiempo **54 → 31 ms** en total contra PostgreSQL por socket Unix local, así
  que la ganancia real con latencia de red será mayor. No se midió con carga productiva.
- **Errores.** `Forbidden`, `NotFound` y `BotMissingPermissions` son `refused`; 400, 429,
  5xx y excepciones propias siguen siendo `error`; las envolturas `CommandInvokeError` se
  desenvuelven. Prueba extremo a extremo: 2 rechazos + 1 fallo + 1 éxito da tasa de fallo
  50 % y 50 % de rechazos, y el filtro `refused` los muestra. No hay cambio de esquema.
- **Cohortes.** `baseline` y `joined_observed` (pruebas con línea base, con datos
  expirados por retención y con un reingreso detectado por inventario previo).
- **Interfaz.** Avisos con porcentaje y duración de huecos, comparaciones marcadas como
  aproximadas o ausentes, columna de origen en cohortes, columna de rechazos de Discord.
  Chromium: 2 pruebas (vacío/móvil/XSS/notas de antes y una nueva con datos sembrados).

Ejecución: `tests/test_studio.py` + `tests/test_studio_browser.py` = **23 correctas**.
Suite completa en este entorno: **2287 correctas, 20 omitidas, 2 fallidas**. Las dos
fallas son `test_migrate_r2_buckets.py` por falta de `pg_dump` en el entorno (no hay
clientes PostgreSQL), no relacionadas con Studio. Ruff (check y format) y `node --check`
pasan.

Pendiente para la validación final: repetir en el Compose documentado (Python 3.14 y
clientes PostgreSQL 18) para confirmar esas 2 pruebas y la versión de intérprete; la
suite de ese entorno ya no será de 2.275 pruebas sino algunas más por las añadidas.
Sin verificar: carga real del bot, PostgreSQL nativo del host y corte eléctrico.

## Cuarta sesión: validación final e integración controlada

Fecha: 4 de noviembre de 2026. Base principal verificada con `git ls-remote`:
`main` = `59aca3212ac7488e084f52d8ed3f9531761666d6` (sin avances desde la copia).

### Entorno reproducido
Docker **no** se pudo usar: el daemon está activo, pero `/var/run/docker.sock` es
`root:docker`, el usuario de desarrollo no pertenece al grupo `docker` y `sudo` exige
contraseña. No se modificó el host. Se reprodujo el contenido del Compose sin
contenedores y fuera del repositorio: Python 3.14.10 (uv), PostgreSQL 18.6 (binarios
embebidos), clientes `pg_dump`/`pg_restore` 18.6 (paquete PGDG extraído, sin instalar),
`age` 1.3.2, `pytest` 9.1.1, Playwright con Chromium, `.pyc` en un directorio limpio
(los del repositorio venían del contenedor de la sesión original). Diferencias respecto
al Compose: sistema operativo del host en lugar de `python:3.14-slim`, y PostgreSQL por
loopback TCP.

### Resultados
| Entorno | Resultado |
|---|---|
| Python 3.14.10 + PostgreSQL 18.6 + clientes 18.6 + `age` + Chromium (suite completa, antes de los últimos cambios) | **2.309 correctas, 0 omitidas, 0 fallidas** |
| `test_migrate_r2_buckets.py` (las 2 pendientes) | **39/39 correctas** con `pg_dump` disponible |
| Python 3.12.16 + PostgreSQL 16.15 (piso de compatibilidad de CI; sin Playwright) | **2.317 correctas, 2 omitidas (Chromium), 0 fallidas** |
| `deploy/backup_db_test.sh` | OK (requiere la base `purgito_restorecheck` creada previamente) |
| Ruff check/format, `build_docs.py --check`, tests JS de landing, `node --check studio/studio.js`, `git diff --check` | correctos |
| `shellcheck` | **no ejecutado**: no está instalado; no hay `.sh` modificados |

Las cifras finales tras los cambios de esta sesión están en la sección «Ejecución final».
Ningún fallo fue introducido por Studio; los dos fallos de la sesión anterior eran de
entorno (faltaba `pg_dump`).

### Defecto real corregido
`measure_delivery` registraba como **éxito** una entrega cancelada (`CancelledError` es
`BaseException`: no entraba en el `except Exception`, pero sí en el `finally`). Reproducido
antes del arreglo; ahora una cancelación no se registra. Prueba:
`test_cancelled_delivery_is_not_recorded_as_success`.

### Pruebas añadidas (ciclo de vida y seguridad)
Studio desactivado por defecto (no engancha hooks ni escribe); configuración inválida
(5 variantes) nunca rompe el arranque; base de datos caída al arrancar deja el bot
funcionando sin Studio; arranque y apagado cierran la tarea de escritura y vuelcan lo
pendiente; un peer no loopback recibe 404 aunque lleve token y `Host` loopback válidos.

### Cambios de redacción de la sesión
Una comparación con cobertura parcial se presenta como «solo lo observado», no como
estimación representativa y sin prueba de significancia. Se retiró del panel una frase
sobre datos históricos con otra clasificación de errores: Studio nunca estuvo en
producción, así que no existe ese salto en datos reales (sí en bases de desarrollo).

### Coste medido
- Almacenamiento: 633 B por fila de `studio_usage` incluyendo índices. Cota alta
  sintética (126 servidores activos todos los días con 20 claves por servidor y día,
  90 días): 226.800 filas ≈ 144 MB. Un uso real será menor; crece con servidores × claves.
- Esquema: las 8 tablas se crean en ~7 ms sin tocar las existentes.
- Ciclo del worker: ~50 ms con 3.000 claves y 200 servidores; ~0,2 ms en reposo
  (sesión anterior). `record()` ≈ 1,2 µs por evento. Sin medir con carga productiva.

### Procedimiento de integración (no ejecutado; requiere aprobación)
1. Rama local `feat/purgito-studio` desde `main` (`59aca32`), con rutas explícitas (nunca
   `git add -A`). Quedan fuera el registro del proceso de reconstrucción
   (`STUDIO_RECOVERY.md`), `data/`, `.venv/`, cachés y `__pycache__`.
2. PR hacia `main`: CI ejecuta Ruff, la suite con PostgreSQL, los tests JS y CodeQL.
   Los tests de Chromium se omiten en CI (Playwright opcional).
3. Antes de desplegar: backup con `deploy/backup_db.sh` y `deploy/preflight_check.sh`.
4. Despliegue estándar (`git pull` + reinicio manual) **sin** `STUDIO_*` en el `.env`.
   Verificar: el bot arranca, `/health` responde, los comandos habituales funcionan,
   `/internal/studio/report` da 404 y existen las 8 tablas `studio_*` vacías.
5. Activación, en una operación aparte: añadir `STUDIO_ENABLED=true` y `STUDIO_HMAC_KEY`
   (≥ 32 caracteres, guardada fuera de Git; no se puede rotar sin perder la continuidad
   de cohortes), reiniciar y consultar `/internal/studio/report` por loopback. Revisar
   durante 24 h `collector.dropped = 0` y `last_error = null`, y la latencia de comandos.
6. Abrir el panel solo por túnel SSH a `127.0.0.1:18081`; no publicar el puerto.

### Reversión
Ver «Desactivar y retirar Studio» en `STUDIO.md`: apagar (`STUDIO_ENABLED=false`),
volver al commit anterior, y solo con aprobación borrar las tablas. Cada nivel se
comprobó en una base desechable (tablas y filas del bot idénticas antes y después).

### Ejecución final (tras todos los cambios de esta sesión)
- Python 3.14.10 + PostgreSQL 18.6 + clientes 18.6 + `age` + Chromium: **2.319 correctas,
  0 omitidas, 0 fallidas** (suite completa, 71 s, bytecode limpio).
- Python 3.12.16 + PostgreSQL 16.15: **2.317 correctas, 2 omitidas (Chromium), 0 fallidas**.
- Ruff, formato, `build_docs.py --check`, tests JS de landing, `node --check`,
  `git diff --check` y `deploy/backup_db_test.sh`: correctos.
- No ejecutado: contenedores Docker/Compose (permiso del socket), `shellcheck`, carga
  real del bot, PostgreSQL nativo del host y corte eléctrico.

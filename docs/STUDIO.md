# Purgito Studio — instalación privada y contrato de datos

Studio está **desactivado por defecto** y no se ha ejecutado en producción. Los
resultados de las pruebas y sus límites están en [la validación](STUDIO_VALIDATION.md).

## Arquitectura

Python + discord.py + aiohttp y el pool asyncpg de `db.get_db()`. No hay otro
PostgreSQL, exportador, servicio SaaS, framework de frontend ni autenticación de
usuarios nueva. Los eventos operativos, Prometheus y el monitor externo mantienen
su función. **Los registros de producto no pasan por `events.log_event`, JSONL,
Vector ni el monitor externo**. Se guardan únicamente en tablas `studio_*` del
PostgreSQL del bot.

`runtime.Collector.record()` agrega en memoria sin SQL, red ni `await`. Un worker
vuelca cada 10 s con timeout y transacción. El bot sigue funcionando si falla
Studio. El buffer se acota a 4096 claves pendientes, más un lote en vuelo y un
inventario; las repeticiones incrementan un contador, no crean una lista de eventos.
Los descartes se muestran en el estado del colector y se persisten en la sesión.

En reposo no hay escrituras de datos: un ciclo sin eventos solo avanza la cobertura
de la sesión (sin fila de ledger), y el inventario se reescribe únicamente si cambió
el conjunto de servidores o el día. Por eso `observed_at` de un inventario es el
momento del último cambio observado ese día, no del último ciclo.

El ledger `studio_batches` evita sumar dos veces si el servidor confirmó una
transacción pero el cliente perdió la respuesta. Un cierre ordenado intenta
vaciar el lote en vuelo y el buffer antes de cerrar el pool. **No es una cola
WAL duradera**: un SIGKILL o corte puede perder lo no confirmado desde el último
flush; la sesión conserva su último intervalo confirmado y no se inventa lo que
pasó después. Tampoco se reconstruyen eventos ocurridos con el bot apagado.
La espera inicial y las desconexiones del gateway no cuentan como cobertura:
una reconexión abre otra sesión de captura sin rellenar ese intervalo.

## Instalar después de revisar y autorizar

No ejecutar estos pasos de instalación sobre producción sin autorización.

1. Instalar el código revisado con las dependencias existentes de
   `requirements.txt`. No se añade ninguna dependencia de runtime.
2. Mantener el `DATABASE_URL` existente. `init_db()` aplica las tablas idempotentes
   de `schema_pg.sql`; no cambia tablas ni históricos del resto del bot.
3. En el `.env` privado de la instancia, habilitar:

```dotenv
STUDIO_ENABLED=true
STUDIO_HMAC_KEY=<secreto aleatorio estable de al menos 32 caracteres>
STUDIO_RETENTION_DAYS=90
STUDIO_VERSION=<versión desplegada opcional; por defecto commit de Git>
OBSERVABILITY_TOKEN=<el token privado existente de observabilidad>
```

Generar la clave HMAC con `python -c 'import secrets; print(secrets.token_hex(32))'`
en una terminal privada, nunca guardarla en un archivo versionado. Es distinta del
token de acceso. Sin clave válida Studio no arranca, pero el bot sí. Un cambio de
clave frente a un fingerprint existente se rechaza: no mezclar cohortes como si
fueran comunidades nuevas. Para reiniciar voluntariamente la cobertura, exportar
solo agregados anónimos si hacen falta, borrar las tablas Studio dentro de una
operación aprobada y empezar una medición nueva; no borrar tablas del bot.

4. Reiniciar el bot mediante el procedimiento manual existente. Consultar por
   loopback, sin exponer el token en argumentos compartidos o logs:

```bash
curl -H "Authorization: Bearer $OBSERVABILITY_TOKEN" \
  http://127.0.0.1:8080/internal/studio/report
```

5. Ejecutar la interfaz privada en el mismo host:

```bash
.venv/bin/python scripts/studio.py --backend-port 8080 --port 18081
```

Solo escucha en **127.0.0.1**. Para abrirla desde tu ordenador:

```bash
ssh -L 18081:127.0.0.1:18081 <usuario>@<host-privado>
```

Abrir `http://127.0.0.1:18081`. El navegador pide usuario **admin** y como contraseña
el **OBSERVABILITY_TOKEN existente**. La autenticación Basic solo cruza loopback o
el túnel cifrado SSH. No publicar el puerto ni ponerlo detrás del proxy público.
El companion convierte la credencial ya validada en el Bearer que entiende el
backend; no gestiona usuarios, sesiones ni contraseñas nuevas. No utiliza la sesión
OAuth de los administradores de servidores de Discord: esa autorización no da
acceso a analítica global. Solo entregar el token a operadores autorizados.

La interfaz vive en `studio/`, **fuera de `landing/`**. No se añade una página de
estadísticas al sitio público. El backend sigue siendo solo JSON. El gate existente
se combina con la comprobación del peer y Host loopback; cabeceras de proxy,
credenciales ausentes o incorrectas y contenido JSON inválido se rechazan. Las
anotaciones usan además Origin/Fetch-Site y una cabecera de escritura explícita en
el companion. CSP, no-store y ausencia de scripts externos se aplican a toda la UI.

## Qué se mide

- **Instalados:** tamaño del inventario observado de `bot.guilds`. El primer
  inventario es una línea base, nunca nuevas instalaciones.
- **Entradas / salidas:** eventos reales `guild_join` / `guild_remove`. Una
  reconexión no los sintetiza. Ausencias durante un apagado no se atribuyen a un
  instante inventado. La diferencia entre inventarios no se convierte en eventos.
- **Reingresos:** una entrada posterior a una salida previamente observada dentro
  de los datos retenidos; no prueba que fuera la segunda instalación de toda la vida.
- **Comunidad activa:** al menos un comando, respuesta a mención o trigger exitoso.
  No cuentan entregas programadas, mensajes espontáneos ni comandos rechazados.
- **Adopción:** comunidades con alguna ejecución o entrega exitosa de la función / comunidades distintas presentes
  en inventarios de los días del período, con el filtro de versión. Las entregas de fondo cuentan como función utilizada, pero no como comunidad activa. No hay un
  denominador de elegibilidad por permisos o Premium. Si el inventario no permite
  sostener el cálculo se devuelve `null`, no un porcentaje forzado.
- **Usos:** ejecuciones instrumentadas de comandos y entregas de producto. No es
  número de personas ni de mensajes de conversación. Los envíos en varios chunks
  cuentan como una entrega lógica en el chat.
- **Fallos:** fallos de ejecución / (éxitos + fallos). Tres resultados quedan fuera de
  esa tasa y siguen visibles y filtrables: `rejected` (validación previa: permisos de
  quien invoca, argumentos, cooldown), `refused` (Discord rechazó la acción por la
  configuración del servidor: `Forbidden` 403, `NotFound` 404 o el bot sin permisos)
  y los propios éxitos. Se decide solo por el tipo de excepción, nunca por su texto,
  y no se guarda código de estado ni mensaje. Todo lo demás (400 por un payload
  inválido, 429, 5xx, errores de red, excepciones propias) es `error`: son fallos que
  Purgito debe atender aunque el origen sea Discord. Además del porcentaje de fallo
  se informa `refused_pct` = rechazos / (éxitos + fallos + rechazos). **Los datos
  guardados antes de este cambio contaban `Forbidden`/`NotFound` como fallo**; no se
  reescriben. Studio aún no se ha ejecutado en producción, así que los datos reales
  nacerán con esta clasificación y no habrá salto: el aviso solo afecta a bases de
  desarrollo anteriores. Cualquier cambio futuro de clasificación debe registrarse como
  anotación de tipo `release` para que quede identificado en el panel.
- **Latencias:** para comandos, desde el hook previo hasta completion/error; para
  entregas, tiempo del envío instrumentado. Las validaciones anteriores al hook no
  tienen latencia inventada. Media ponderada y p95 aproximado por buckets
  25/50/100/250/500/1000/2500/5000/10000/30000/>30000 ms. Duraciones no finitas o
  superiores a una hora no se incorporan a muestras de latencia.
- **Cohortes:** instalación observada y primera actividad observada son distintas;
  la segunda **no** significa que el bot se incorporó ese día. Cada cohorte de
  actividad indica `baseline` (su día es el primer día de datos disponibles, es decir
  el inicio de la medición o el límite de retención: son servidores que ya existían,
  no nuevos) y `joined_observed` (cuántos tienen un `guild_join` retenido: la única
  incorporación verificable). Un `guild_join` de un servidor que ya figuraba en un
  inventario anterior se guarda como reingreso, no como entrada nueva.
  D1/D7/D28 mide retorno en el día UTC exacto, no uso continuo ni «regresó alguna vez».
  La actividad se puede producir con una versión posterior a la de la cohorte.
  El target debe haber terminado, tener inventario y cobertura continua confirmada
  del colector sin descartes; si no, queda censurado y el porcentaje es `null`.
  Primera actividad significa primera **en los datos retenidos**, no primer uso
  histórico. Los servidores de la línea base no tienen fecha de instalación nueva.

El catálogo de comandos sale de los comandos registrados, sin parámetros. Los
adaptadores actuales cubren prefijo y slash, respuestas del chat (mención, trigger,
espontáneo y GIF), entrega de memes por trigger y avisos entregados de YouTube,
Twitch y RSS. No se convierte toda línea de log, formulario o mensaje recibido en
un «uso». Las excepciones anteriores a un adaptador de entrega y acciones internas
no instrumentadas siguen en observabilidad operativa; no se presentan como éxitos
ni como ceros verificados de todas las funcionalidades posibles. La tabla indica
la cobertura por función; sin comandos registrados ni adaptador, muestra «Sin
instrumentar», no un cero de adopción.

## Interfaz y filtros

Resumen, Comunidades, Retención, Funciones, Calidad, Versiones y Actualizaciones.
Filtros de período UTC, versión, función y resultado. Comparación anterior de igual
duración o una ventana personalizada anterior de igual longitud. Los datos de uso
son horarios: se ajusta el comienzo hacia abajo y el fin a la última hora completa;
la respuesta muestra los límites efectivos. Las anotaciones conservan su hora
exacta hasta el fin solicitado. Máximo 90 días por ventana.

**Cobertura y comparación.** La cobertura de un período es la fracción de su duración
cubierta por sesiones de captura confirmadas; cada hueco se lista con su duración y
nunca se rellena ni se interpreta como cero. Estados (umbrales en `studio/model.py`):
`complete` ≥ 99,5 % y sin registros descartados; `partial` ≥ 90 % (o completa con
descartes); `unavailable` < 90 %. La comparación entre períodos es `comparable` si
ambos son completos; `partial` si ambos son ≥ 90 % pero alguno no completo (se muestran diferencia y
porcentaje con la leyenda «solo lo observado», sin extrapolar: lo observado es un mínimo
del uso real y no es una estimación representativa; tampoco hay prueba de significancia); y
`not_comparable` si alguno es < 90 %: sin diferencia ni porcentaje, aunque los valores
observados siguen visibles. Un reinicio de segundos o minutos ya no invalida la
comparación; un corte de varios días sí la degrada. Un cero de adopción solo se
declara con cobertura completa. La retención D1/D7/D28 conserva su regla estricta
(día objetivo con cobertura continua e inventario), sin tolerancia a huecos.
Una base anterior cero no da un «crecimiento infinito»: porcentaje `null`. Los
inventarios son puntos observados diarios, no una serie interpolada. La versión y
las anotaciones permiten interpretar un cambio, no demostrar causalidad. El filtro
de función aplica al uso/cohorte de actividad, no a los movimientos globales de
instalación. Un cero se etiqueta como «sin uso observado» cuando no hay cobertura
suficiente. Las pantallas no generan registros de ejemplo ni rellenan históricos.

Las anotaciones permiten marcar releases y cambios relevantes; se almacenan como
texto plano y se renderizan con `textContent`. No pegar conversaciones, tokens ni
información personal en ellas. El archivo local ignorado
`data/studio_manual_observations.json` recoge únicamente los 120 y 126 comunicados
por el propietario, **sin fechas** y sin importarlos a las tablas.

## Retención, privacidad y borrado

Se persisten: hora UTC, HMAC de servidor, función y comando registrado, fuente,
resultado, versión, conteos e histogramas. También inventarios diarios con HMAC,
transiciones mínimas, sesiones de captura, ledger idempotente y notas privadas.
No se guardan IDs de persona, nombres de servidores, canales, texto, argumentos,
URLs de contenido ni excepciones con texto libre en las tablas Studio. Las claves
de servidor nunca salen en respuestas de la API. El HMAC evita exponer snowflakes,
pero sigue siendo pseudonimización, no anonimización irreversible.

El worker elimina a diario los datos fuera de `STUDIO_RETENTION_DAYS` (90 por
defecto, configurable entre 7 y 365), incluida la presencia vinculada a inventarios.
Las notas y el ledger también caducan. Las sesiones de captura que todavía abarcan
el presente se conservan para evaluar cobertura; no contienen identidades de guild.
El fingerprint de la clave no caduca para detectar rotaciones accidentales.
Puede ejecutarse `await Store(...).cleanup()` desde un procedimiento administrativo
local aprobado. Los backups existentes pueden contener agregados anteriores: usar
la política de backups del proyecto y volver a ejecutar limpieza tras restaurarlos.

Para detener la recopilación, `STUDIO_ENABLED=false` y reiniciar: los hooks no
capturan y los endpoints responden 404. La retención automática requiere el worker
activo; para borrar datos con Studio apagado, realizar limpieza administrativa.
La desactivación no borra silenciosamente una medición previa.

## Desactivar y retirar Studio

Tres niveles, de menos a más destructivo. Los dos primeros no tocan datos del bot.

1. **Apagar la recopilación** (reversible): `STUDIO_ENABLED=false` (o quitar la
   variable) y reiniciar con el procedimiento manual existente. Los hooks no se
   instalan, `/internal/studio/*` responde 404 y los datos ya guardados se conservan.
   Sin worker no hay limpieza de retención.
2. **Volver al código anterior**: desplegar el commit previo a la integración. El
   código antiguo ignora las tablas `studio_*` (comprobado: su esquema se reaplica
   sobre una base que las conserva).
3. **Borrar los datos de Studio** (destructivo; solo con aprobación): las ocho tablas son
   independientes del resto del esquema, así que basta
   `DROP TABLE IF EXISTS studio_presence, studio_inventory, studio_usage,
   studio_lifecycle, studio_batches, studio_sessions, studio_annotations, studio_meta
   CASCADE;`. Comprobado en una base desechable: el resto de tablas y sus filas quedan
   idénticas. Los backups hechos mientras Studio estuvo activo conservan sus agregados
   hasta que caduquen por la política de backups.

**El esquema se aplica al arrancar aunque Studio esté desactivado**: `init_db()` ejecuta
`schema_pg.sql` en cada arranque y crea las ocho tablas vacías (`CREATE TABLE IF NOT
EXISTS`, ~7 ms, sin tocar tablas existentes). «Desactivado» significa sin recopilación
ni endpoints, no «sin tablas».

## Validación reproducible

Usar **solo TEST_DATABASE_URL** de una base desechable llamada `purgito_test`;
`conftest.py` la asigna a DATABASE_URL antes de importar el bot y trunca tablas.
Nunca indicar una base de producción.

```bash
TEST_DATABASE_URL=<postgresql de pruebas> WEB_PORT=18080 \
  .venv/bin/python -m pytest tests/test_studio.py -q
.venv/bin/python -m pytest tests -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python landing/build_docs.py --check
node landing/test_lang.mjs
node landing/test_dash.mjs
node landing/test_historial.mjs
node --check studio/studio.js
.venv/bin/python scripts/benchmark_studio.py --events 20000
```

Prueba opcional real de Chromium (dependencias solo de desarrollo): instalar
`playwright`, ejecutar `python -m playwright install --with-deps chromium` y correr
`pytest tests/test_studio_browser.py`. Usa backend y DB reales de pruebas, revisa
las siete vistas, filtros, anotaciones, persistencia de notas, XSS y ancho móvil.
Las capturas vacías se guardan en `data/studio-preview-*.png` (ignoradas por Git).
El benchmark es sintético, solo mide enqueue en memoria y no escribe en PostgreSQL;
no reutiliza ni confirma el supuesto resultado de 11 µs del asistente anterior.

### Entorno de desarrollo reproducible sin PostgreSQL del host

```bash
docker compose -f studio/development.compose.yml run -T --build --rm tests
docker compose -f studio/development.compose.yml run --rm tests ruff check .
docker compose -f studio/development.compose.yml down -v
```

El compose usa Python 3.14, PostgreSQL 18 y sus clientes pg_dump/pg_restore,
una red privada para la base, sin puertos publicados, y una base en tmpfs que se pierde al
parar. El contenedor de tests tiene salida para las comprobaciones DNS de la suite
preexistente de GIFs; Studio no exporta telemetría. No lee credenciales de producción. El montaje del proyecto es la copia de
desarrollo, necesaria para revisar archivos y resultados; no apuntarlo al checkout
productivo. No habilita Studio en un bot ni inicia sesión en Discord.

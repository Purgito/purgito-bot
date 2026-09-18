# Auditoría de reliability — resumen ejecutivo (Ronda 1)

Fecha: 2026-09-18. A diferencia de `AUDITORIA_SEGURIDAD.md` (mentalidad red
team: "¿puede alguien explotar esto?") y `AUDITORIA_UX.md` (mentalidad
primera impresión: "¿el texto es humano?"), esta auditoría es de
**reliability**: para cada punto donde el bot hace algo no trivial, se
preguntó sistemáticamente

> excepción → ¿qué ve el usuario? → ¿qué ve el log? → ¿queda algún estado roto?

con foco en las cuatro superficies que más separan "tiene muchas funciones"
de "se siente como un producto": tareas en background, webhooks, comandos y
configuración. `AUDITORIA_UX.md` hallazgo #1 (sin manejador global de
errores para slash commands → "La aplicación no respondió") es el ejemplo
que motivó esta ronda — ya estaba resuelto en el código
(`cogs/general.py::on_app_command_error`, registrado en `cog_load` como
`bot.tree.on_error`) antes de esta sesión, sin que el propio
`AUDITORIA_UX.md` lo marcara como cerrado. Esta ronda encontró y cerró la
misma clase de problema en dos superficies que el fix original no cubría.

---

## 1. Alcance revisado

- **Tareas en background** (`@tasks.loop`, 11 en total en 8 cogs): ¿qué
  pasa si el cuerpo del loop tira una excepción sin atrapar? ¿el loop
  vuelve a correr solo, o queda muerto para siempre sin que nadie se entere?
- **Componentes interactivos** (botones, selects, modals — `discord.ui.View`
  / `discord.ui.Modal`, ~12 clases entre `settings.py`, `layout_buttons.py`,
  `privacy.py`, `help_view.py`): ¿qué pasa si un callback o un `on_submit`
  tira una excepción? ¿es el mismo mecanismo que ya protege a los slash
  commands, o uno separado?
- **La API/dashboard como superficie de configuración** (`webapi.py`, ~80
  endpoints): ¿qué responde un handler que tira una excepción sin atrapar?
  ¿el body sigue siendo el JSON que el resto del contrato de la API
  promete?
- **Comandos** (slash + prefijo): el handler global ya existe
  (`on_app_command_error` para slash, `on_command_error` para prefijo) —
  verificado que sigue andando, no re-auditado a fondo porque
  `AUDITORIA_UX.md` hallazgo #1 y su test (`test_error_handler.py`) ya lo
  cubren con detalle.

**Fuera de alcance / diferido en esta ronda:**

- **Webhooks de Polar** (`_webhook_polar`): ya recibió una auditoría de
  seguridad completa y específica (`AUDITORIA_SEGURIDAD.md` Sección 2, 3
  rondas) que cubre exactamente el mismo eje pregunta por pregunta
  (payloads malformados → 400 en vez de 500 sin control, idempotencia,
  logging de eventos ignorados a nivel `info`). No hay nada nuevo que
  agregar acá sin repetir ese trabajo.
- **`resolve_gifs_task` (`cogs/gifs.py`): un GIF permanentemente
  irresolvable ocupa un lugar en la cola para siempre.** Encontrado durante
  esta ronda, no corregido todavía — ver §6 (deuda conocida). No es una
  excepción sin atajar (el propio `resolve_media_url` ya atrapa todo y
  devuelve `None`), así que no encaja en el patrón "excepción →
  usuario/log/estado roto" que es el eje de esta ronda, pero es la misma
  familia de problema (degradación silenciosa) y vale la pena dejarlo
  anotado para no perderlo.
- **Barrido completo de los ~80 endpoints de la API** buscando lógica de
  negocio específica que deje estado a medias (más allá del error
  genérico): la Sección 3 de `AUDITORIA_SEGURIDAD.md` ya cubrió a fondo el
  eje "secuencia partida en varios locks" para SQLite, que es la forma más
  común de estado roto en este codebase. Esta ronda se concentró en la capa
  de arriba (qué pasa cuando algo revienta), no en repetir ese barrido.

---

## 2. Hallazgos

| # | Área | Severidad | Problema | Fix | Residual conocido |
|---|---|---|---|---|---|
| 1 | Componentes (botones/selects/modals) | **Alta** | `View.on_error`/`Modal.on_error` son mecanismos separados de `bot.tree.on_error` (que sí cubre slash commands desde el fix de `AUDITORIA_UX.md` #1) — el default de discord.py para estos dos solo loguea, nunca responde. Ninguna de las ~12 clases de View/Modal del bot lo sobreescribía: una excepción en cualquier callback de botón o en `on_submit` dejaba al usuario viendo el "Esta interacción falló" nativo de Discord, sin ninguna explicación, exactamente en las superficies de más contacto (el panel `/settings`, `/setup`, la bienvenida, borrar mis datos, `/help`, los botones de rol/modal de Layout V2) | `SafeView`/`SafeModal` (`utils.py`): clases base con `on_error` conectado a un helper compartido (`report_component_error`) que loguea con traceback y responde/hace followup un mensaje humano, respetando si la interacción ya fue respondida/diferida (mismo criterio que `on_app_command_error`). Las ~12 clases pasan a heredar de estas en vez de `discord.ui.View`/`discord.ui.Modal` directo | Ninguno conocido — cubre toda excepción no atajada en el callback/`on_submit` mismo. Un test de cobertura (`test_todas_las_views_y_modals_del_bot_heredan_de_safeview_safemodal`) recorre `__subclasses__()` sobre los cogs reales para que una View/Modal nueva sin heredar de estas bases haga fallar la suite |
| 2 | API/dashboard (`webapi.py`) | Media | Una excepción no atajada en cualquiera de los ~80 handlers no pasaba por ningún middleware propio: aiohttp responde por su cuenta con `Content-Type: text/plain` y un body que no es JSON (confirmado contra un server aiohttp mínimo). El dashboard (`apiFetch`) espera poder hacerle `.json()` a cualquier respuesta de error — con un body de texto plano eso tira una excepción de parseo en el navegador, así que el usuario ni siquiera llega a ver el "Error 500" pelado que ya señalaba `AUDITORIA_UX.md` hallazgo #10, sino una pantalla rota sin ningún mensaje | `_error_middleware` nuevo, montado como la capa más interna (después de `_security_headers_middleware`/`_cors_middleware`) para que su respuesta de error siga saliendo con esas cabeceras: atrapa cualquier `Exception` que no sea `web.HTTPException` (las deliberadas — 404, redirects de `/auth/*` — pasan intactas), loguea con `log.exception` (método + path) y devuelve `{"error": "ocurrió un error inesperado, intenta de nuevo más tarde"}` con status 500 | Ninguno conocido para el contrato JSON. Un bug dentro de `_security_headers_middleware`/`_cors_middleware` mismos (antes de llamar al handler) seguiría sin cubrirse — son dos funciones simples, el riesgo es bajo, no se tocó |

---

## 3. El hallazgo más importante

El hallazgo #1 es, otra vez, el mismo patrón que ya cerró
`AUDITORIA_UX.md` (mismo síntoma: "la aplicación no respondió" / "esta
interacción falló") pero en una superficie que el fix original no tocaba
porque discord.py separa los dos mecanismos de raíz. Vale la pena remarcar
el paralelismo con `AUDITORIA_SEGURIDAD.md` Sección 3: ahí el patrón
repetido era "un lock que protege cada paso individualmente no protege la
secuencia completa"; acá es "un handler de errores que cubre un tipo de
interacción no cubre las demás, aunque se sientan como 'lo mismo' para
quien lo usa". En los dos casos, el bug sobrevive porque cada pieza mirada
aislada parece correcta — `on_app_command_error` está perfectamente bien
escrito, simplemente discord.py nunca lo llama para un click de botón.

El blast radius es mayor que el del hallazgo original de UX: los ~25 slash
commands se usan, pero el panel `/settings` (con sus 8 modals anidados),
`/setup`, la bienvenida y los botones de rol/modal de Layout V2 son
justamente las superficies con MÁS pasos secuenciales (varios clicks,
formularios) donde hay más oportunidad de que algo falle a mitad de camino
— y hasta ahora, cualquier falla ahí era invisible para el usuario y solo
detectable revisando logs a mano.

---

## 4. Estado final verificable

- **Tests:** 1663 → 1676 (**+13 tests nuevos**): 8 en
  `test_component_error_handler.py` (incluye el test de cobertura por
  `__subclasses__()`) y 5 en `test_api_error_middleware.py`. Número base
  (1663) es el de la suite completa al cierre de la Sección 3 de
  `AUDITORIA_SEGURIDAD.md`, en esta misma sesión.
- **Corridas de verificación:** suite completa corrida antes y después de
  cada uno de los dos fixes.
- **Lint/format:** `ruff check .` y `ruff format --check .` limpios contra
  la versión pineada en CI (`ruff==0.15.8`).
- **`landing/build_docs.py --check`:** no aplica — esta ronda no tocó
  `landing/`, `docs/*.md` de cara al usuario ni ningún `.css`/`.js`.

---

## 5. Decisiones tomadas sin pedir permiso explícito en el momento

1. **`SafeView`/`SafeModal` como clases base nuevas en `utils.py`**, en vez
   de agregar un `on_error` repetido a cada una de las ~12 clases: son
   demasiadas para justificar la duplicación, y una base compartida hace
   que una View/Modal futura lo herede gratis en vez de depender de que
   quien la escriba se acuerde.
2. **Mensaje genérico de error** ("ocurrió un error inesperado, intenta de
   nuevo más tarde" en la API; el ya existente `general.error.generic` en
   componentes) — mismo criterio de "Voz y copy" de CLAUDE.md que ya usa
   `on_app_command_error`, no un texto nuevo inventado para esta ronda.
3. **Orden de `_error_middleware` en la lista de middlewares** (después de
   CORS y cabeceras de seguridad, no antes): para que la respuesta 500 que
   arma siga recibiendo esas cabeceras en vez de salir pelada. Verificado
   con un test que chequea el orden real en `_runner.app.middlewares`, no
   solo que la función exista.

---

## 6. Deuda o limitaciones conocidas que quedaron fuera

- **`resolve_gifs_task` (`cogs/gifs.py:634`): un GIF cuyo `resolve_media_url`
  devuelve `None` de forma permanente (host no soportado, link muerto)
  ocupa uno de los 25 lugares de cada corrida cada 90 segundos, para
  siempre.** `get_unresolved_gifs` hace `ORDER BY id LIMIT 25` sobre
  `media_url IS NULL` — no hay backoff ni límite de reintentos, así que si
  se acumulan 25+ filas permanentemente irresolubles, los GIFs nuevos
  (`id` más alto) nunca llegan a entrar en la cola y quedan con
  `media_url` en NULL indefinidamente. No es una excepción sin atajar (ya
  está bien manejada), es degradación silenciosa por acumulación — mismo
  espíritu que los hallazgos #8 y similares de `AUDITORIA_UX.md`
  ("memes automáticos que nunca postean, sin aviso"), pero del lado de
  datos en vez de UX directa. Impacto práctico hoy: no medido (no hay
  forma barata de saber cuántas filas están en ese estado sin correr la
  query a mano). Candidato fuerte para la próxima ronda de reliability.
- **`_security_headers_middleware`/`_cors_middleware` sin su propia red de
  contención.** Si alguna de las dos tirara una excepción ANTES de llamar
  a `handler(request)` (hoy no lo hacen — son funciones simples que arman
  headers), `_error_middleware` no la vería, al estar montado más adentro.
  Riesgo aceptado: ambas son código estable y no han cambiado en las
  últimas rondas de auditoría.
- **Comandos de prefijo (`!ping`, etc.):** `on_command_error` en
  `cogs/general.py` cubre los casos conocidos (`MissingPermissions`,
  `CommandNotFound`, `MissingRequiredArgument`) pero cualquier otra
  excepción solo se loguea (`log.error(..., exc_info=error)`) sin avisar
  al usuario. No se tocó en esta ronda: los comandos de prefijo son un
  vestigio (`!ping`), no la superficie principal (esa es slash + el panel),
  y agregar un catch-all ahí sin confirmarlo primero podía interferir con
  el manejo específico que ya existe. Queda anotado, no resuelto.

---

## 7. Próxima ronda

Esta ronda cerró la brecha más grande y de mayor blast radius (componentes
sin manejador de error) y una brecha estructural en el contrato de la API
(respuestas de error que no son JSON). Candidatos concretos para la
siguiente pasada, de mayor a menor impacto estimado:

1. **`resolve_gifs_task`** (arriba, §6) — acotar con un límite de
   reintentos o un backoff, para que un puñado de GIFs irresolubles no le
   quiten cupo a los nuevos indefinidamente.
2. **Revisar el resto de tareas en background que SÍ tienen `.error()`**
   (`test_task_loop_error_handlers.py` ya confirma que las 7 que lo
   necesitan lo tienen) por el ángulo "¿y si la excepción es sistemática,
   no transitoria?" — un `.restart()` automático ante un bug real
   (no un `sqlite3.OperationalError` transitorio) reintenta para siempre
   sin que nadie se entere, en vez de fallar visiblemente después de N
   intentos.
3. **`on_command_error` de comandos de prefijo** (arriba, §6) — decidir
   si vale la pena un catch-all humano ahí, dado que la superficie es
   chica.
